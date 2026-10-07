"""The skill installer's follow-ups from PR #82 (app/skills/install.py, app/digest/propose.py):
a shell grant in allowed-tools is the owner's, the final move never replaces anything, and a
quoted path cannot speak for a proposal.

Every skill here is a tiny fake written in tmp_path, built with tests/test_skill_install.py's
helpers; nothing is ever moved by os.rename into the skills directory."""

from __future__ import annotations

import ctypes
import errno
import json
import os
from pathlib import Path

import pytest

from app.digest import propose
from app.digest.model import Finding, Location
from app.digest.selfmodel import build_self_model
from app.skills import install as installer
from app.skills.install import INSTALLED, NOT_APPROVED, REFUSED, install
from tests.test_digest_relate import REPO_ROOT, fixture_memory
from tests.test_skill_install import (
    FORGED_FOLDERS,
    STAR,
    _anchor,
    _approved,
    _digested,
    _proposed,
    _reasoning,
    _skill_md,
    _synthetic,
)

SKILL_MD = "skills/star-charts/SKILL.md"
MARKER = " Target builder_skill: "
LABELS = (" Needs the owner: ", " Licence: ", " Hypothesis: ", " Measure: ", " Removal: ", " Rank: ")
# The sentence CLIVE writes for why a builder skill from another artifact needs the owner.
BUILDER_SKILL = ("a builder skill from another artifact steers every builder that loads it, and "
                 "its instructions are that artifact's words, not CLIVE's")


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    return build_self_model(REPO_ROOT, memory=fixture_memory(tmp_path_factory.mktemp("memory")))


def _staging(skills_dir: Path) -> list[str]:
    return [name for name in os.listdir(skills_dir) if name.startswith(installer.STAGING_PREFIX)]


# --- F4: a shell grant is the owner's -----------------------------------------------------------


SHELL_GRANTS = {
    "inline": ("allowed-tools: Read, Bash\n", "Bash"),
    "pattern": ("allowed-tools: Bash(npm:*)\n", "Bash(npm:*)"),
    "flow-list": ("allowed_tools: [Grep, shell]\n", "shell"),
    "block-list": ("allowed-tools:\n  - Read\n  - PowerShell\n", "PowerShell"),
    "any-case": ("Allowed-Tools: Terminal\n", "Terminal"),
    "after-dots": ("...\nallowed-tools: Bash\n", "Bash"),
}


@pytest.mark.parametrize("case", sorted(SHELL_GRANTS))
def test_a_skill_whose_allowed_tools_grant_a_shell_tool_is_the_owners(tmp_path, case):
    extra, grant = SHELL_GRANTS[case]
    files = {SKILL_MD: _skill_md("star-charts", extra=extra)}
    store, quarantine, artifact_id, _units = _approved(tmp_path / "a", files)
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    [outcome] = install(store, quarantine, artifact_id, skills_dir)
    assert (outcome.status, outcome.kind) == (REFUSED, "owner"), outcome
    assert outcome.approved_by == "owner"
    assert grant in outcome.reason and SKILL_MD in outcome.reason, outcome.reason
    assert not os.path.lexists(skills_dir / "star-charts")
    assert os.listdir(skills_dir) == []


@pytest.mark.parametrize("severity", ["low", "medium", "high", "critical"])
def test_a_stored_agent_permissions_finding_in_the_folder_is_the_owners(tmp_path, severity):
    store, quarantine, artifact_id, _units = _approved(tmp_path / "a", STAR)
    store.add_finding(Finding(artifact_id, "safety", severity, Location(SKILL_MD, 4, 4),
                              "execute.agent_permissions: shell commands without asking."))
    [outcome] = install(store, quarantine, artifact_id, tmp_path / "skills")
    assert (outcome.status, outcome.kind) == (REFUSED, "owner")
    assert "execute.agent_permissions" in outcome.reason and SKILL_MD in outcome.reason
    assert not (tmp_path / "skills").exists()


def test_a_skill_granting_no_shell_tool_installs_and_records_its_allowed_tools(tmp_path):
    files = {SKILL_MD: _skill_md("star-charts", extra="allowed-tools: Read, Grep\n")}
    store, quarantine, artifact_id, _units = _approved(tmp_path / "a", files)
    skills_dir = tmp_path / "skills"
    [outcome] = install(store, quarantine, artifact_id, skills_dir)
    assert outcome.status == INSTALLED, outcome
    record = json.loads((skills_dir / "star-charts" / "provenance.json").read_text(encoding="utf-8"))
    assert record["allowed_tools"] == "Read, Grep"
    assert os.listdir(skills_dir) == ["star-charts"]


# --- F6: the final move never replaces ----------------------------------------------------------


def _appear(final: Path, filled: bool) -> None:
    final.mkdir()
    if filled:
        (final / "mine.txt").write_text("mine\n", encoding="utf-8")


def _state(folder: Path) -> dict[str, tuple[bytes | None, int, int, int]]:
    out = {".": (None, folder.lstat().st_ino, folder.lstat().st_mtime_ns, folder.lstat().st_mode)}
    for path in sorted(folder.rglob("*")):
        info = path.lstat()
        out[path.relative_to(folder).as_posix()] = (
            path.read_bytes() if path.is_file() else None, info.st_ino, info.st_mtime_ns, info.st_mode)
    return out


def _conflict_left_as_it_was(tmp_path: Path, monkeypatch, attribute: str, wrap, filled: bool) -> None:
    store, quarantine, artifact_id, _units = _approved(tmp_path / "a", STAR)
    skills_dir = tmp_path / "skills"
    final = skills_dir / "star-charts"
    seen: list[dict] = []

    def appear() -> None:
        _appear(final, filled)
        seen.append(_state(final))

    monkeypatch.setattr(installer, attribute, wrap(getattr(installer, attribute), appear))
    [outcome] = install(store, quarantine, artifact_id, skills_dir)
    assert (outcome.status, outcome.kind) == (REFUSED, "conflict"), outcome
    assert "appeared while the skill was staged; nothing is overwritten" in outcome.reason
    [before] = seen
    assert _state(final) == before
    assert sorted(os.listdir(final)) == (["mine.txt"] if filled else [])
    assert os.listdir(skills_dir) == ["star-charts"] and _staging(skills_dir) == []


@pytest.mark.parametrize("filled", [False, True], ids=["empty", "non-empty"])
def test_a_folder_made_at_the_final_name_after_the_checks_is_a_conflict(tmp_path, monkeypatch, filled):
    """Made once the staging folder is sealed: the check before the move gives the clear message."""
    def wrap(real, appear):
        def seal_then_appear(staging):
            real(staging)
            appear()
        return seal_then_appear

    _conflict_left_as_it_was(tmp_path, monkeypatch, "_seal", wrap, filled)


@pytest.mark.parametrize("filled", [False, True], ids=["empty", "non-empty"])
def test_a_folder_made_at_the_final_name_just_before_the_move_is_never_replaced(
        tmp_path, monkeypatch, filled):
    """Made after the check, just before the real renameat2: the move itself refuses (EEXIST),
    where os.rename would have replaced an empty folder silently."""
    def wrap(real, appear):
        def lookup():
            function = real()
            assert function is not None, "libc has no renameat2 here"

            def renameat2(*args):
                appear()
                return function(*args)
            return renameat2
        return lookup

    _conflict_left_as_it_was(tmp_path, monkeypatch, "_renameat2", wrap, filled)


def _failing(code: int):
    def renameat2(*_args):
        ctypes.set_errno(code)
        return -1
    return lambda: renameat2


@pytest.mark.parametrize("lookup", [lambda: None, _failing(errno.ENOSYS), _failing(errno.EINVAL)],
                         ids=["no-renameat2", "ENOSYS", "EINVAL"])
def test_without_the_move_that_never_replaces_nothing_is_installed(tmp_path, monkeypatch, lookup):
    store, quarantine, artifact_id, _units = _approved(tmp_path / "a", STAR)
    skills_dir = tmp_path / "skills"
    renamed: list[tuple] = []
    real_rename = os.rename

    def spy(*args, **kwargs):
        renamed.append(args)
        return real_rename(*args, **kwargs)

    monkeypatch.setattr(installer, "_renameat2", lookup)
    monkeypatch.setattr(os, "rename", spy)
    [outcome] = install(store, quarantine, artifact_id, skills_dir)
    monkeypatch.undo()
    assert (outcome.status, outcome.kind) == (REFUSED, "held"), outcome
    assert "never replaces" in outcome.reason and "not available" in outcome.reason
    assert renamed == []
    assert not os.path.lexists(skills_dir / "star-charts")
    assert os.listdir(skills_dir) == []


def test_any_other_failure_of_the_move_is_raised_and_leaves_nothing(tmp_path, monkeypatch):
    store, quarantine, artifact_id, _units = _approved(tmp_path / "a", STAR)
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(installer, "_renameat2", _failing(errno.EACCES))
    with pytest.raises(OSError) as raised:
        install(store, quarantine, artifact_id, skills_dir)
    assert raised.value.errno == errno.EACCES
    assert os.listdir(skills_dir) == []


# --- a quoted path cannot speak for a proposal ------------------------------------------------


def test_inert_makes_the_space_after_every_colon_a_no_break_space():
    assert propose.inert("x Needs the owner: y Licence: z:w") == (
        "x Needs the owner: y Licence: z:w")
    assert propose.inert("MIT") == "MIT"


FOLDERS = {**FORGED_FOLDERS, "third-marker": "x Target builder_skill: y"}


@pytest.mark.parametrize("forged", sorted(FOLDERS))
def test_a_licence_declared_in_a_forged_folder_cannot_speak_for_the_proposal(tmp_path, model, forged):
    folder = FOLDERS[forged]
    store, _quarantine, artifact_id = _digested(
        tmp_path, model, curated=False, files={f"skills/{folder}/SKILL.md": _skill_md("star-charts")})
    unit = _anchor(store, artifact_id, "star-charts")
    [proposal] = [p for p in store.absorptions(artifact_id)
                  if p.unit_id == unit.id and p.target == "builder_skill"]
    text = proposal.reasoning
    assert propose.inert(folder) in text and folder not in text
    assert propose.needs_owner(proposal)
    assert propose.explain(proposal).needs_owner == BUILDER_SKILL
    assert not installer.is_curated(proposal)
    assert text.count(MARKER) == 1
    after = text[text.index(MARKER) + len(MARKER) - 1:]
    assert all(after.count(label) <= 1 for label in LABELS), after


def _trunk_forged(folder: str) -> str:
    """A reasoning as trunk's propose wrote it for a skill whose licence is declared in folder:
    CLIVE's Needs-the-owner clause, then the folder quoted raw in the Licence clause."""
    return _reasoning(needs=BUILDER_SKILL).replace(SKILL_MD, f"skills/{folder}/SKILL.md")


@pytest.mark.parametrize("forged", sorted(FOLDERS))
def test_a_reasoning_in_trunks_forged_shape_needs_the_owner_and_is_not_curated(tmp_path, forged):
    reasoning = _trunk_forged(FOLDERS[forged])
    assert FOLDERS[forged] in reasoning
    store, quarantine, artifact_id, units = _synthetic(tmp_path / "a", STAR)
    proposal = _proposed(store, artifact_id, units["star-charts"], reasoning)
    assert propose.needs_owner(proposal)
    assert propose.explain(proposal).needs_owner == propose.AMBIGUOUS
    assert not installer.is_curated(proposal)
    [outcome] = install(store, quarantine, artifact_id, tmp_path / "skills")
    assert outcome.status == NOT_APPROVED and not outcome.approved
    assert not (tmp_path / "skills").exists()


def test_a_reasoning_that_repeats_no_label_reads_as_before(tmp_path):
    store, _quarantine, artifact_id, units = _synthetic(tmp_path / "a", STAR)
    plain = _proposed(store, artifact_id, units["star-charts"],
                      _reasoning(why="The skill becomes one builder skill." + propose.CURATED))
    parts = propose.explain(plain)
    assert parts.needs_owner == "" and not propose.needs_owner(plain)
    assert parts.licence.startswith("MIT: keep") and parts.rank.startswith("0.50")
    assert installer.is_curated(plain)
