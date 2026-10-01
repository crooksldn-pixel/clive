"""The skill installer (app/skills/install.py, scripts/skills.py): the digester's approved skills,
installed byte for byte into CLIVE's git-ignored skills directory with provenance and licence,
and uninstalled cleanly.

Every skill here is a tiny fake written in tmp_path. The collection is taken in end to end
through intake.intake (the directory handler) and pipeline.digest(curated=True), as
tests/test_digest_curated.py does; the edge cases use a store built by hand, with synthetic
ledger records and findings over a quarantined copy pinned by its tree digest. Nothing here
serves on a socket."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.digest import propose
from app.digest.adapters.skills import SCRIPT_SUFFIXES
from app.digest.intake import intake
from app.digest.model import (
    ADDING_TARGETS,
    Absorption,
    Addition,
    Artifact,
    Finding,
    Location,
    RemovalHandle,
    Source,
    Unit,
)
from app.digest.pipeline import digest, tree_digest
from app.digest.selfmodel import build_self_model
from app.digest.store import DigestStore
from app.skills import install as installer
from app.skills.install import (
    ALREADY,
    DEFAULT_SKILLS_DIR,
    DEFERRED,
    INSTALLED,
    NOT_APPROVED,
    REFUSED,
    CopyMismatch,
    SkillsDirRefused,
    UninstallRefused,
    install,
    installed,
    uninstall,
)
from tests.test_digest_relate import REPO_ROOT, fixture_memory

APP_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = APP_ROOT / "scripts" / "skills.py"
RECORDED = "2026-10-01T09:00:00+00:00"
LATER = "2026-10-01T10:00:00+00:00"
LATEST = "2026-10-01T11:00:00+00:00"

SKILLS = {
    "star-charts": ("Draw star charts for any night sky.",
                    ("Plot the stars", "Label the constellations", "Export the chart")),
    "tide-tables": ("Read tide tables for a stretch of coast.",
                    ("Find the harbour", "Read high water", "Allow for the moon")),
}


def _skill_md(name: str, extra: str = "", body: str = "") -> str:
    description, steps = SKILLS.get(name, ("Draw star charts.", ("Plot the stars",)))
    return (f"---\nname: {name}\ndescription: {description}\nlicense: MIT\n{extra}---\n# {name}\n\n"
            "## Steps\n\n" + "".join(f"{n}. {step}.\n" for n, step in enumerate(steps, 1)) + body)


COLLECTION = {
    "skills/star-charts/SKILL.md": _skill_md(
        "star-charts", body="\nSee [the reference](reference.md) for the magnitudes.\n"),
    "skills/star-charts/reference.md": "# Magnitudes\n\nBrighter stars have lower magnitudes.\n",
    "skills/tide-tables/SKILL.md": _skill_md("tide-tables"),
}


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    return build_self_model(REPO_ROOT, memory=fixture_memory(tmp_path_factory.mktemp("memory")))


def _write(base: Path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return base


def _digested(base: Path, model, *, curated: bool = True) -> tuple[DigestStore, Path, str]:
    """The fake collection, taken in and digested into a store: (store, quarantine root, id)."""
    tree = _write(base / "tree", COLLECTION)
    quarantine = base / "quarantine"
    taken = intake(tree, quarantine, kind="directory")
    store = DigestStore(base / "store")
    digest(taken.path, taken.source, store, self_model=model, recorded_at=RECORDED,
           withheld=taken.withheld, notes=taken.notes, curated=curated)
    return store, quarantine, taken.artifact_id


def _anchor(store: DigestStore, artifact_id: str, name: str) -> Unit:
    [unit] = [u for u in store.load(artifact_id).units
              if f"skill:{name}" in u.tags and u.kind == "knowledge" and u.location.path.endswith("SKILL.md")]
    return unit


def _decide(store: DigestStore, artifact_id: str, unit: Unit, target: str, at: str) -> Absorption:
    removal = RemovalHandle((Addition("skill", ".claude/skills/decided"),) if target in ADDING_TARGETS else ())
    record = Absorption(artifact_id, unit.id, target, "The owner decided it.", removal, at,
                        decided_by="owner")
    assert store.add_absorption(record)
    return record


def _synthetic(base: Path, files: dict[str, str | bytes], *, skills: dict[str, str] | None = None,
               links: tuple[tuple[str, str], ...] = (), modes: dict[str, int] | None = None,
               licence: str | None = "MIT") -> tuple[DigestStore, Path, str, dict[str, Unit]]:
    """A store built by hand over a quarantined copy pinned by its tree digest, with one
    SKILL.md knowledge unit per skill and nothing in the ledger."""
    skills = skills or {"star-charts": "skills/star-charts/SKILL.md"}
    tree = _write(base / "staged", files)
    for link, target in links:
        os.symlink(target, tree / link)
    for rel, mode in (modes or {}).items():
        os.chmod(tree / rel, mode)
    source = Source("https://example.invalid/skills.git", "git", "0" * 40, licence, RECORDED,
                    tree_digest(tree))
    quarantine = base / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    os.rename(tree, quarantine / source.artifact_id)
    units = {name: Unit(source.artifact_id, "knowledge", name, f"{name}: a fake skill.",
                        Location(path, 1, 5), ("skill", f"skill:{name}"))
             for name, path in skills.items()}
    store = DigestStore(base / "store")
    store.put(Artifact(source, ("skill_collection",), tuple(units.values())))
    return store, quarantine, source.artifact_id, units


def _approved(base: Path, files: dict[str, str | bytes], **given):
    """A synthetic store whose skills the owner has approved."""
    store, quarantine, artifact_id, units = _synthetic(base, files, **given)
    for unit in units.values():
        _decide(store, artifact_id, unit, "builder_skill", RECORDED)
    return store, quarantine, artifact_id, units


STAR = {"skills/star-charts/SKILL.md": _skill_md("star-charts")}


def _reasoning(*, subject: str = "The skill 'star-charts' (1 piece of knowledge)",
               why: str = "The skill becomes one builder skill.", needs: str = "") -> str:
    """A reasoning in propose's shape (propose._reasoning)."""
    hypothesis, measure = propose.usual_hypothesis("builder_skill")
    parts = [f"{subject} is a gap: nothing in CLIVE shares enough with it (closest: none).",
             f"Target builder_skill: {why}"]
    if needs:
        parts.append(f"{propose.NEEDS_OWNER}: {needs}.")
    parts += ["Licence: MIT: keep its copyright and licence notice (skills/star-charts/SKILL.md) "
              "with what is added.",
              f"Hypothesis: {hypothesis}", f"Measure: {measure}",
              "Removal: take out skill .claude/skills/star-charts-00000000 (the digest of each is "
              "recorded when it is written); the suite stays green afterwards.",
              "Rank: 0.50 (target value 1.00, relation 0.30, substance 0.30, cost 1.00)",
              f"Self-model sha256:{'0' * 64}. Proposed by CLIVE; the owner decides."]
    return " ".join(parts)


def _proposed(store: DigestStore, artifact_id: str, unit: Unit, reasoning: str) -> Absorption:
    record = Absorption(artifact_id, unit.id, "builder_skill", reasoning,
                        RemovalHandle((Addition("skill", ".claude/skills/star-charts"),)), RECORDED)
    assert store.add_absorption(record)
    return record


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _files(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*"))
            if p.is_file() and not p.is_symlink()}


def _snapshot(folder: Path) -> dict[str, tuple[bytes | None, int]]:
    return {p.relative_to(folder).as_posix(): (p.read_bytes() if p.is_file() else None,
                                               p.stat().st_mtime_ns)
            for p in sorted(folder.rglob("*"))}


def _by_name(outcomes) -> dict:
    return {outcome.name: outcome for outcome in outcomes}


# --- the end-to-end collection ----------------------------------------------------------------


def test_a_curated_collection_installs_both_skills_byte_for_byte_with_provenance(tmp_path, model):
    store, quarantine, artifact_id = _digested(tmp_path, model)
    skills_dir = tmp_path / "skills"
    outcomes = _by_name(install(store, quarantine, artifact_id, skills_dir))
    assert {name: o.status for name, o in outcomes.items()} == {name: INSTALLED for name in SKILLS}
    source = store.load(artifact_id).source
    ledger = store.absorptions(artifact_id)
    for name, (description, _steps) in SKILLS.items():
        assert outcomes[name].approved_by == "curated" and outcomes[name].path == skills_dir / name
        quarantined = quarantine / artifact_id / "skills" / name
        copy = skills_dir / name / "skill"
        assert tree_digest(copy) == tree_digest(quarantined)
        expected = _files(quarantined)
        assert _files(copy) == expected and "SKILL.md" in expected
        for path in copy.rglob("*"):
            assert stat.S_IMODE(path.lstat().st_mode) == (0o555 if path.is_dir() else 0o444)
        assert stat.S_IMODE(copy.lstat().st_mode) == 0o555
        assert not (skills_dir / name / "licence").exists()

        record = json.loads((skills_dir / name / "provenance.json").read_text(encoding="utf-8"))
        assert record["schema"] == "clive.skill_install.v1" and record["name"] == name
        assert record["route"] == "instructions" and record["description"] == description
        assert record["allowed_tools"] is None and record["installed_at"]
        assert record["source"] == {
            "origin": source.origin, "origin_kind": "directory", "pinned_ref": source.pinned_ref,
            "content_digest": source.content_digest, "taken_at": source.taken_at,
        }
        assert record["skill"] == {
            "path_in_artifact": f"skills/{name}", "digest": tree_digest(quarantined),
            "files": [{"path": rel, "sha256": _sha(data), "bytes": len(data)}
                      for rel, data in sorted(expected.items())],
        }
        assert record["licence"] == {"expression": "MIT", "declared_in": f"skills/{name}/SKILL.md",
                                     "copied": []}
        unit = _anchor(store, artifact_id, name)
        [proposal] = [p for p in ledger if p.unit_id == unit.id and p.target == "builder_skill"]
        assert record["digest_record"] == {
            "artifact_id": artifact_id, "unit_id": unit.id, "proposal_id": proposal.id,
            "decision_id": None, "approved_by": "curated",
        }
    assert [record["name"] for record in installed(skills_dir)] == sorted(SKILLS)


def test_without_curated_only_the_owners_last_decision_installs(tmp_path, model):
    store, quarantine, artifact_id = _digested(tmp_path, model, curated=False)
    skills_dir = tmp_path / "skills"
    outcomes = install(store, quarantine, artifact_id, skills_dir)
    assert {o.status for o in outcomes} == {NOT_APPROVED} and len(outcomes) == 2
    assert not skills_dir.exists()

    unit = _anchor(store, artifact_id, "star-charts")
    decision = _decide(store, artifact_id, unit, "builder_skill", LATER)
    outcomes = _by_name(install(store, quarantine, artifact_id, skills_dir))
    assert outcomes["star-charts"].status == INSTALLED and outcomes["tide-tables"].status == NOT_APPROVED
    record = json.loads((skills_dir / "star-charts" / "provenance.json").read_text(encoding="utf-8"))
    [proposal] = [p for p in store.absorptions(artifact_id)
                  if p.unit_id == unit.id and p.target == "builder_skill" and not p.is_decision]
    assert record["digest_record"] == {
        "artifact_id": artifact_id, "unit_id": unit.id, "proposal_id": proposal.id,
        "decision_id": decision.id, "approved_by": "owner",
    }
    assert not (skills_dir / "tide-tables").exists()

    # a later owner decision with another target withholds it again
    _decide(store, artifact_id, unit, "reference_only", LATEST)
    again = _by_name(install(store, quarantine, artifact_id, skills_dir))["star-charts"]
    assert again.status == NOT_APPROVED and "reference_only" in again.reason


# --- what counts as curated -------------------------------------------------------------------


def test_a_curated_proposal_in_propose_shape_is_approved_as_curated(tmp_path):
    store, quarantine, artifact_id, units = _synthetic(tmp_path, STAR)
    proposal = _proposed(store, artifact_id, units["star-charts"],
                         _reasoning(why="The skill becomes one builder skill." + propose.CURATED))
    [outcome] = install(store, quarantine, artifact_id, tmp_path / "skills")
    assert outcome.status == INSTALLED and outcome.approved_by == "curated"
    record = json.loads((tmp_path / "skills" / "star-charts" / "provenance.json").read_text())
    assert record["digest_record"]["proposal_id"] == proposal.id
    assert record["digest_record"]["decision_id"] is None


@pytest.mark.parametrize("reasoning", [
    # the artifact's own words, before the marker, say curated
    _reasoning(subject=f"The skill '{propose.CURATED.strip()}'"),
    # curated, but the reasoning says it needs the owner
    _reasoning(why="The skill becomes one builder skill." + propose.CURATED,
               needs="its licence sets conditions"),
    # clipped: no Hypothesis, Measure or Removal
    "The skill 'star-charts' is a gap. Target builder_skill: The skill becomes one builder skill."
    + propose.CURATED,
    # the curated sentence only before the marker, and none after it
    f"{propose.CURATED.strip()} Target builder_skill: The skill becomes one builder skill. "
    "Hypothesis: h. Measure: m. Removal: r.",
], ids=["title", "needs-owner", "clipped", "before-marker"])
def test_a_proposal_that_is_not_curated_is_not_installed(tmp_path, reasoning):
    store, quarantine, artifact_id, units = _synthetic(tmp_path, STAR)
    _proposed(store, artifact_id, units["star-charts"], reasoning)
    [outcome] = install(store, quarantine, artifact_id, tmp_path / "skills")
    assert outcome.status == NOT_APPROVED and not outcome.approved
    assert not (tmp_path / "skills").exists()


# --- held, the owner's, deferred ---------------------------------------------------------------


def test_a_skill_from_a_blocked_artifact_is_held(tmp_path):
    store, quarantine, artifact_id, _units = _approved(tmp_path, STAR)
    store.add_finding(Finding(artifact_id, "safety", "critical", Location("."),
                              "deceptive.bidi: a direction override."))
    [outcome] = install(store, quarantine, artifact_id, tmp_path / "skills")
    assert (outcome.status, outcome.kind) == (REFUSED, "held") and "blocked" in outcome.reason
    assert not (tmp_path / "skills").exists()


@pytest.mark.parametrize("severity", ["high", "critical"])
def test_a_skill_with_a_high_or_critical_finding_in_its_folder_is_held(tmp_path, severity):
    files = {**STAR, "skills/tide-tables/SKILL.md": _skill_md("tide-tables")}
    store, quarantine, artifact_id, _units = _approved(
        tmp_path, files, skills={"star-charts": "skills/star-charts/SKILL.md",
                                 "tide-tables": "skills/tide-tables/SKILL.md"})
    store.add_finding(Finding(artifact_id, "safety", severity, Location("skills/tide-tables/SKILL.md", 9, 9),
                              "injection.override: text aimed at an agent. Only the skill folder is held."))
    outcomes = _by_name(install(store, quarantine, artifact_id, tmp_path / "skills"))
    if severity == "critical":       # a critical finding is a blocked artifact: everything is held
        assert outcomes["star-charts"].kind == "held" and "blocked" in outcomes["tide-tables"].reason
        assert not (tmp_path / "skills").exists()
    else:                            # a high one holds only the skill folder it is in
        assert outcomes["star-charts"].status == INSTALLED
        assert "injection.override" in outcomes["tide-tables"].reason
    assert (outcomes["tide-tables"].status, outcomes["tide-tables"].kind) == (REFUSED, "held")
    assert not (tmp_path / "skills" / "tide-tables").exists()


OWNER_CASES = {
    "hooks": ({"skills/star-charts/SKILL.md": _skill_md(
        "star-charts", extra="hooks:\n  PreToolUse:\n    - command: echo hi\n")}, (), None),
    "command": ({"skills/star-charts/SKILL.md": _skill_md(
        "star-charts", body="\nThe branch: !`git branch --show-current`\n")}, (), None),
    "link": (STAR, (("skills/star-charts/peer.md", "SKILL.md"),), None),
    "secret": (STAR, (), "secret.github_token"),
    "mcp": (STAR, (), "execute.mcp"),
    "agent_hook": (STAR, (), "execute.agent_hook"),
    "agent_settings": (STAR, (), "execute.agent_settings"),
    "binary": (STAR, (), "execute.binary"),
}


@pytest.mark.parametrize("case", sorted(OWNER_CASES))
def test_a_skill_that_would_run_on_its_own_or_brings_a_key_is_the_owners(tmp_path, case):
    files, links, rule = OWNER_CASES[case]
    store, quarantine, artifact_id, _units = _approved(tmp_path, files, links=links)
    if rule is not None:
        store.add_finding(Finding(artifact_id, "safety", "medium",
                                  Location("skills/star-charts/SKILL.md", 2, 2), f"{rule}: found here."))
    [outcome] = install(store, quarantine, artifact_id, tmp_path / "skills")
    assert (outcome.status, outcome.kind) == (REFUSED, "owner"), outcome
    assert outcome.approved
    assert not (tmp_path / "skills").exists()


def test_a_skill_whose_licence_forbids_reuse_is_the_owners(tmp_path):
    files = {"skills/star-charts/SKILL.md": _skill_md("star-charts").replace(
        "license: MIT", "license: LicenseRef-Proprietary")}
    store, quarantine, artifact_id, _units = _approved(tmp_path, files)
    [outcome] = install(store, quarantine, artifact_id, tmp_path / "skills")
    assert (outcome.status, outcome.kind) == (REFUSED, "owner") and "forbids reuse" in outcome.reason
    assert not (tmp_path / "skills").exists()


DEFERRED_CASES = {
    **{f"suffix{suffix}": ({f"skills/star-charts/helper{suffix}": "x = 1\n"}, None,
                           f"skills/star-charts/helper{suffix}") for suffix in sorted(SCRIPT_SUFFIXES)},
    "scripts-run-py": ({"skills/star-charts/scripts/run.py": "print('plot')\n"}, None,
                       "skills/star-charts/scripts/run.py"),
    "shebang": ({"skills/star-charts/bin/plot": b"#!/bin/sh\necho plot\n"}, None,
                "skills/star-charts/bin/plot"),
    "executable": ({"skills/star-charts/data.txt": "1 2 3\n"}, {"skills/star-charts/data.txt": 0o755},
                   "skills/star-charts/data.txt"),
}


@pytest.mark.parametrize("case", sorted(DEFERRED_CASES))
def test_a_skill_carrying_scripts_is_deferred_with_the_file_named(tmp_path, case):
    extra, modes, named = DEFERRED_CASES[case]
    store, quarantine, artifact_id, _units = _approved(tmp_path, {**STAR, **extra}, modes=modes)
    [outcome] = install(store, quarantine, artifact_id, tmp_path / "skills")
    assert (outcome.status, outcome.kind) == (DEFERRED, "scripts") and named in outcome.files
    assert not (tmp_path / "skills").exists()


def test_a_stored_script_finding_defers_and_at_most_five_files_are_named(tmp_path):
    extra = {f"skills/star-charts/tool{n}.py": "x = 1\n" for n in range(7)}
    store, quarantine, artifact_id, _units = _approved(tmp_path, {**STAR, "skills/star-charts/Makefile": "all:\n"}
                                                       | extra)
    store.add_finding(Finding(artifact_id, "safety", "medium", Location("skills/star-charts/Makefile"),
                              "execute.makefile: a Makefile."))
    [outcome] = install(store, quarantine, artifact_id, tmp_path / "skills")
    assert outcome.status == DEFERRED and len(outcome.files) == 5
    assert outcome.files[0] == "skills/star-charts/Makefile"


# --- the copy, the licence, idempotence, conflict -----------------------------------------------


def test_a_quarantined_copy_that_no_longer_matches_installs_nothing(tmp_path, model):
    store, quarantine, artifact_id = _digested(tmp_path, model)
    copy = quarantine / artifact_id
    os.chmod(copy, 0o755)
    (copy / "extra.md").write_text("changed after it was pinned\n", encoding="utf-8")
    with pytest.raises(CopyMismatch):
        install(store, quarantine, artifact_id, tmp_path / "skills")
    assert not (tmp_path / "skills").exists()
    done = _cli("install", artifact_id, "--store", store.root, "--quarantine", quarantine,
                "--skills-dir", tmp_path / "skills", cwd=tmp_path)
    assert done.returncode == 1 and "nothing of the artifact is installed" in done.stderr
    assert not (tmp_path / "skills").exists()


def test_a_licence_outside_the_skill_folder_is_copied_with_its_notice(tmp_path):
    licence = ("MIT License\n\nCopyright (c) 2026 Example\n\n"
               "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
               "of this software and associated documentation files (the \"Software\"), to deal\n"
               "in the Software without restriction, including without limitation the rights\n"
               "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
               "copies of the Software.\n")
    files = {"LICENSE": licence, "NOTICE": "Example skills, 2026.\n",
             "skills/star-charts/SKILL.md": _skill_md("star-charts").replace("license: MIT\n", "")}
    store, quarantine, artifact_id, _units = _approved(tmp_path, files)
    [outcome] = install(store, quarantine, artifact_id, tmp_path / "skills")
    assert outcome.status == INSTALLED
    folder = tmp_path / "skills" / "star-charts"
    assert (folder / "licence" / "LICENSE").read_bytes() == (quarantine / artifact_id / "LICENSE").read_bytes()
    assert (folder / "licence" / "NOTICE").read_bytes() == (quarantine / artifact_id / "NOTICE").read_bytes()
    record = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    assert record["licence"]["expression"] == "MIT" and record["licence"]["declared_in"] == "LICENSE"
    assert [item["path"] for item in record["licence"]["copied"]] == ["licence/LICENSE", "licence/NOTICE"]
    assert record["licence"]["copied"][0]["sha256"] == _sha(licence.encode("utf-8"))
    assert "LICENSE" not in _files(folder / "skill")


def test_without_a_folder_licence_the_sources_licence_is_recorded(tmp_path):
    files = {"skills/star-charts/SKILL.md": _skill_md("star-charts", extra="allowed-tools: Read, Grep\n")
             .replace("license: MIT\n", "")}
    store, quarantine, artifact_id, _units = _approved(tmp_path, files, licence="Apache-2.0")
    [outcome] = install(store, quarantine, artifact_id, tmp_path / "skills")
    assert outcome.status == INSTALLED
    record = json.loads((tmp_path / "skills" / "star-charts" / "provenance.json").read_text())
    assert record["licence"] == {"expression": "Apache-2.0", "declared_in": None, "copied": []}
    assert record["allowed_tools"] == "Read, Grep"


def test_installing_again_writes_nothing_and_another_skill_under_the_name_is_a_conflict(tmp_path):
    store, quarantine, artifact_id, _units = _approved(tmp_path / "a", STAR)
    skills_dir = tmp_path / "skills"
    [first] = install(store, quarantine, artifact_id, skills_dir)
    assert first.status == INSTALLED
    provenance = skills_dir / "star-charts" / "provenance.json"
    before, mtime, listing = provenance.read_bytes(), provenance.stat().st_mtime_ns, sorted(os.listdir(skills_dir))
    [again] = install(store, quarantine, artifact_id, skills_dir)
    assert again.status == ALREADY and again.path == skills_dir / "star-charts"
    assert provenance.read_bytes() == before and provenance.stat().st_mtime_ns == mtime
    assert sorted(os.listdir(skills_dir)) == listing == ["star-charts"]

    other = {"skills/star-charts/SKILL.md": _skill_md("star-charts", body="\nA different skill.\n")}
    store_b, quarantine_b, artifact_b, _units = _approved(tmp_path / "b", other)
    [conflict] = install(store_b, quarantine_b, artifact_b, skills_dir)
    assert (conflict.status, conflict.kind) == (REFUSED, "conflict")
    assert provenance.read_bytes() == before and provenance.stat().st_mtime_ns == mtime
    assert sorted(os.listdir(skills_dir)) == ["star-charts"]

    # a folder that is not an install is a conflict too, and is left as it is
    (skills_dir / "tide-tables").mkdir()
    files = {"skills/tide-tables/SKILL.md": _skill_md("tide-tables")}
    store_c, quarantine_c, artifact_c, _units = _approved(
        tmp_path / "c", files, skills={"tide-tables": "skills/tide-tables/SKILL.md"})
    [refused] = install(store_c, quarantine_c, artifact_c, skills_dir)
    assert refused.kind == "conflict" and os.listdir(skills_dir / "tide-tables") == []


def test_a_name_that_is_not_a_skill_folder_name_is_refused(tmp_path):
    store, quarantine, artifact_id, _units = _approved(
        tmp_path, STAR, skills={"Star_Charts": "skills/star-charts/SKILL.md"})
    [outcome] = install(store, quarantine, artifact_id, tmp_path / "skills")
    assert (outcome.status, outcome.kind) == (REFUSED, "name")
    assert not (tmp_path / "skills").exists()


def test_only_the_skills_named_are_installed(tmp_path, model):
    store, quarantine, artifact_id = _digested(tmp_path, model)
    outcomes = install(store, quarantine, artifact_id, tmp_path / "skills",
                       only=["tide-tables", "no-such-skill"])
    assert [(o.name, o.status) for o in outcomes] == [("tide-tables", INSTALLED),
                                                     ("no-such-skill", NOT_APPROVED)]
    assert os.listdir(tmp_path / "skills") == ["tide-tables"]


# --- uninstall, failures part way, where skills go ---------------------------------------------


def test_uninstall_removes_an_install_wholly_and_says_whether_it_still_matched(tmp_path):
    store, quarantine, artifact_id, _units = _approved(tmp_path, STAR)
    skills_dir = tmp_path / "skills"
    install(store, quarantine, artifact_id, skills_dir)
    removal = uninstall(skills_dir, "star-charts")
    assert removal.removed and removal.matched is True
    assert os.listdir(skills_dir) == []

    install(store, quarantine, artifact_id, skills_dir)
    skill_md = skills_dir / "star-charts" / "skill" / "SKILL.md"
    os.chmod(skill_md, 0o644)
    skill_md.write_text("changed since it was installed\n", encoding="utf-8")
    removal = uninstall(skills_dir, "star-charts")
    assert removal.removed and removal.matched is False and os.listdir(skills_dir) == []

    # a name not installed: nothing changes, and it succeeds
    assert uninstall(skills_dir, "star-charts") == installer.Removal("star-charts", False, None)
    assert os.listdir(skills_dir) == []


def test_uninstall_does_not_say_matched_when_anything_was_added_beside_the_recorded_payload(tmp_path):
    store, quarantine, artifact_id, _units = _approved(tmp_path / "a", STAR)
    skills_dir = tmp_path / "skills"
    for add in (lambda folder: (folder / "extra.txt").write_text("added\n", encoding="utf-8"),
                lambda folder: (folder / "extra").mkdir(),
                lambda folder: (folder / "licence").mkdir(),
                lambda folder: os.symlink(tmp_path, folder / "elsewhere")):
        install(store, quarantine, artifact_id, skills_dir)
        add(skills_dir / "star-charts")
        removal = uninstall(skills_dir, "star-charts")
        assert removal.removed and removal.matched is False and os.listdir(skills_dir) == []

    files = {"LICENSE": "MIT License\n\nCopyright (c) 2026 Example\n",
             "skills/star-charts/SKILL.md": _skill_md("star-charts").replace("license: MIT\n", "")}
    store, quarantine, artifact_id, _units = _approved(tmp_path / "b", files)
    install(store, quarantine, artifact_id, skills_dir)
    licence_dir = skills_dir / "star-charts" / "licence"
    os.chmod(licence_dir, 0o755)
    (licence_dir / "EXTRA").write_text("added\n", encoding="utf-8")
    removal = uninstall(skills_dir, "star-charts")
    assert removal.removed and removal.matched is False and os.listdir(skills_dir) == []

    install(store, quarantine, artifact_id, skills_dir)
    assert uninstall(skills_dir, "star-charts").matched is True


def test_uninstall_refuses_a_folder_without_provenance_and_a_link(tmp_path):
    skills_dir = tmp_path / "skills"
    (skills_dir / "plain").mkdir(parents=True)
    (skills_dir / "plain" / "notes.md").write_text("mine\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "provenance.json").write_text("{}\n", encoding="utf-8")
    os.symlink(elsewhere, skills_dir / "linked")
    with pytest.raises(UninstallRefused):
        uninstall(skills_dir, "plain")
    with pytest.raises(UninstallRefused):
        uninstall(skills_dir, "linked")
    assert (skills_dir / "plain" / "notes.md").read_text() == "mine\n"
    assert (skills_dir / "linked").is_symlink() and (elsewhere / "provenance.json").exists()
    with pytest.raises(ValueError):
        uninstall(skills_dir, "../elsewhere")


def test_a_failure_part_way_leaves_nothing_behind(tmp_path, monkeypatch):
    store, quarantine, artifact_id, _units = _approved(tmp_path, STAR)
    skills_dir = tmp_path / "skills"

    def broken(staging, record):
        (staging / "provenance.json").write_text("{half", encoding="utf-8")
        raise OSError("the disk filled up")

    monkeypatch.setattr(installer, "_write_provenance", broken)
    with pytest.raises(OSError, match="disk filled up"):
        install(store, quarantine, artifact_id, skills_dir)
    assert os.listdir(skills_dir) == [] and installed(skills_dir) == []
    monkeypatch.undo()

    # a staging folder is never listed, even one holding a whole provenance.json
    [outcome] = install(store, quarantine, artifact_id, skills_dir)
    assert outcome.status == INSTALLED
    staging = skills_dir / ".staging-star-charts-left"
    staging.mkdir()
    (staging / "provenance.json").write_bytes((skills_dir / "star-charts" / "provenance.json").read_bytes())
    assert [record["name"] for record in installed(skills_dir)] == ["star-charts"]


def test_the_default_skills_dir_is_git_ignored_and_the_repository_is_refused(tmp_path):
    assert DEFAULT_SKILLS_DIR == APP_ROOT / ".state" / "skills"
    ignored = (APP_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".state/" in [line.strip() for line in ignored]
    store, quarantine, artifact_id, _units = _approved(tmp_path, STAR)
    inside = APP_ROOT / f"skill-install-test-{uuid.uuid4().hex}"
    try:
        with pytest.raises(SkillsDirRefused):
            install(store, quarantine, artifact_id, inside)
        assert not inside.exists()
        done = _cli("install", artifact_id, "--store", store.root, "--quarantine", quarantine,
                    "--skills-dir", inside, cwd=tmp_path)
        assert done.returncode == 1 and "inside the repository" in done.stderr
        assert not inside.exists()
    finally:
        installer.remove_tree(inside)


# --- the command ------------------------------------------------------------------------------


def _cli(*args: object, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True,
                          text=True, cwd=cwd, timeout=180, check=False)


def test_the_command_installs_lists_and_uninstalls_and_never_writes_the_store(tmp_path, model):
    store, quarantine, artifact_id = _digested(tmp_path, model)
    skills_dir = tmp_path / "skills"
    before = _snapshot(store.root)
    done = _cli("install", artifact_id, "--store", store.root, "--quarantine", quarantine,
                "--skills-dir", skills_dir, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert sorted(done.stdout.splitlines()) == [
        f"installed {name}: approved by curated -> {skills_dir / name}" for name in sorted(SKILLS)]
    again = _cli("install", artifact_id, "--store", store.root, "--quarantine", quarantine,
                 "--skills-dir", skills_dir, "--skill", "star-charts", cwd=tmp_path)
    assert again.returncode == 0 and again.stdout.splitlines() == [
        f"already installed star-charts: {skills_dir / 'star-charts'}"]

    listed = _cli("list", "--skills-dir", skills_dir, cwd=tmp_path)
    assert listed.returncode == 0
    assert [line.split(":")[0] for line in listed.stdout.splitlines()] == sorted(SKILLS)
    assert all(artifact_id in line and "approved by curated" in line for line in listed.stdout.splitlines())

    removed = _cli("uninstall", "star-charts", "--skills-dir", skills_dir, cwd=tmp_path)
    assert removed.returncode == 0 and "still matched" in removed.stdout
    gone = _cli("uninstall", "star-charts", "--skills-dir", skills_dir, cwd=tmp_path)
    assert gone.returncode == 0 and gone.stdout.startswith("not installed star-charts")
    assert sorted(os.listdir(skills_dir)) == ["tide-tables"]

    (skills_dir / "plain").mkdir()
    refused = _cli("uninstall", "plain", "--skills-dir", skills_dir, cwd=tmp_path)
    assert refused.returncode == 2 and (skills_dir / "plain").is_dir()

    missing = _cli("install", "art-" + "0" * 24, "--store", store.root, "--quarantine", quarantine,
                   "--skills-dir", skills_dir, cwd=tmp_path)
    assert missing.returncode == 1
    nowhere = _cli("install", artifact_id, "--store", tmp_path / "no-store", "--quarantine", quarantine,
                   "--skills-dir", skills_dir, cwd=tmp_path)
    assert nowhere.returncode == 1 and not (tmp_path / "no-store").exists()
    bad = _cli("install", artifact_id, "--quarantine", quarantine, cwd=tmp_path)
    assert bad.returncode == 1
    assert _snapshot(store.root) == before


def test_the_command_exits_2_when_an_approved_skill_is_deferred_or_refused(tmp_path):
    files = {**STAR, "skills/star-charts/scripts/run.py": "print('plot')\n"}
    store, quarantine, artifact_id, _units = _approved(tmp_path, files)
    done = _cli("install", artifact_id, "--store", store.root, "--quarantine", quarantine,
                "--skills-dir", tmp_path / "skills", cwd=tmp_path)
    assert done.returncode == 2, done.stderr
    assert done.stdout.splitlines() == [
        "deferred star-charts (scripts): it carries scripts, which wait for a sandboxed script "
        "route: skills/star-charts/scripts/run.py"]
    assert not (tmp_path / "skills").exists()


def test_the_command_prints_no_credential_from_the_artifact(tmp_path):
    token = "ghp_" + "A1b2C3d4E5" * 4
    store, quarantine, artifact_id, _units = _approved(
        tmp_path, STAR, skills={token: "skills/star-charts/SKILL.md"})
    done = _cli("install", artifact_id, "--store", store.root, "--quarantine", quarantine,
                "--skills-dir", tmp_path / "skills", cwd=tmp_path)
    assert done.returncode == 2
    assert token not in done.stdout + done.stderr and "[redacted" in done.stdout
    assert done.stdout.startswith("refused ") and "(name)" in done.stdout
