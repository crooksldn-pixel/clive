"""The skills adapter: agent skills, harness configuration and prompt libraries read into
Units of the right kinds at exact locations — the same Units every time, everything bounded,
nothing executed, imported or written, and what cannot be read said so rather than raised."""

from __future__ import annotations

import ast
import os
import random
import sys
from pathlib import Path

import pytest

from app.digest import Artifact, Source, Unit, content_digest
from app.digest.adapters import skills
from app.digest.model import MAX_BODY, MAX_TITLE, UNIT_KINDS

SOURCE = Source(
    origin="https://example.invalid/skills.git", origin_kind="git",
    pinned_ref="0123456789abcdef0123456789abcdef01234567", licence=None,
    taken_at="2026-09-26T10:00:00+00:00", content_digest=content_digest(b"a skill collection"),
)
ARTIFACT_ID = SOURCE.artifact_id

RELEASE = {
    "skills/release/SKILL.md": (
        "---\n"                                                       # 1
        "name: release\n"
        "description: Cut a release of the package.\n"
        "license: MIT\n"
        "---\n"                                                       # 5
        "# Release\n"
        "\n"
        "Use this skill when a release is due. Never release on a Friday.\n"
        "\n"
        "## Steps\n"                                                  # 10
        "\n"
        "1. Bump the version in `pyproject.toml`.\n"
        "2. Run `scripts/build.sh` to build the wheel.\n"
        "3. Fill in [the notes template](templates/notes.md).\n"
        "\n"                                                          # 15
        "## Rules\n"
        "\n"
        "- Always sign the tag.\n"
        "- Do not publish from a dirty tree.\n"
        "\n"                                                          # 20
        "## Verification\n"
        "\n"
        "- Verify the wheel installs in a clean virtualenv.\n"
        "- The changelog names the version.\n"                       # 24
    ),
    "skills/release/scripts/build.sh": "#!/bin/sh\necho built\n",
    "skills/release/templates/notes.md": "## Notes\n\n- item\n",
}
TRIAGE = {
    "skills/triage/SKILL.md": (
        "---\nname: triage\ndescription: >\n  Sort incoming issues\n  by severity.\n---\n"
        "- Read the issue.\n- Label it.\n- You must link a duplicate when there is one.\n"
    ),
}
HARNESS = {
    "CLAUDE.md": (
        "# Project notes\n\nAlways run `make test` before committing.\n\n"
        "## Workflow\n\n1. Create a branch.\n2. Make the change.\n3. Run the tests.\n\n"
        "## Don'ts\n\n- Never force-push to main.\n"
    ),
    "AGENTS.md": (
        "## Rules\n\n- Do not edit generated files.\n\n"
        "## Release process\n\n1. Update the changelog.\n2. Tag the release.\n"
    ),
    ".cursor/rules/python.mdc": (
        '---\ndescription: Python style\nglobs: "**/*.py"\nalwaysApply: false\n---\n'
        "- Always use type hints.\n"
    ),
    ".cursorrules": "Never commit secrets.\n",
}
PROMPTS = {
    "prompts/library.md": (
        "# Prompts\n\n## Summarise\n\nSummarise the text below in three bullet points.\n\n"
        "## Translate\n\nTranslate the text below into French.\nKeep the tone.\n"
    ),
    "prompts.json": (
        '[\n  {"name": "haiku", "prompt": "Write a haiku about {topic}."},\n'
        '  "Explain {concept} to a child.",\n  {"name": "empty"}\n]\n'
    ),
    "prompts/roles.json": (
        '{\n  "prompts": {\n    "critic": "Criticise the draft.",\n    "editor": {\n'
        '      "template": "Edit the draft."\n    }\n  }\n}\n'
    ),
    "prompts/chat.jsonl": (
        '{"act": "Linux terminal", "prompt": "Act as a Linux terminal."}\nnot json\n'
        '"Plain prompt."\n'
    ),
    "system.prompt": "You are a careful reviewer.\n---\nSecond prompt here.\n",
    ".claude/commands/review.md": (
        "---\ndescription: Review the diff\n---\n# Review\n\nReview the diff for bugs.\n"
    ),
    "prompts/extra.yaml": "- prompt: hello\n",
}


def _write(root: Path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return root


def _everything(root: Path) -> Path:
    return _write(root, {**RELEASE, **TRIAGE, **HARNESS, **PROMPTS})


def _digest(root: Path) -> list[Unit]:
    return skills.decompose(root, ARTIFACT_ID)


def _summary(units: list[Unit], path: str | None = None) -> list[tuple]:
    return [
        (u.kind, u.title, u.location.path, u.location.line_start, u.location.line_end)
        for u in units if path is None or u.location.path == path
    ]


def _unparsed(units: list[Unit], path: str) -> list[Unit]:
    return [u for u in units if "unparsed" in u.tags and u.location.path == path]


# --- the contract ------------------------------------------------------------------------------


def test_the_adapter_names_itself_and_lives_in_a_namespace_package():
    assert isinstance(skills.NAME, str) and skills.NAME
    assert isinstance(skills.HANDLES, tuple) and skills.HANDLES
    assert all(isinstance(kind, str) and kind for kind in skills.HANDLES)
    assert not (Path(skills.__file__).parent / "__init__.py").exists()


def test_the_adapter_handles_the_kinds_recognition_and_the_model_name():
    from app.digest import detect
    from app.digest.model import ARTIFACT_KINDS

    ours = {"agent_skill", "skill_collection", "agent_config"}
    assert ours <= {registration.kind for registration in detect.registered()}
    assert ours <= set(skills.HANDLES)
    assert set(skills.HANDLES) & set(ARTIFACT_KINDS) == {"skill_collection"}


def test_an_artifact_id_that_is_not_one_is_refused(tmp_path):
    with pytest.raises(ValueError):
        skills.decompose(tmp_path, "not-an-id")


# --- skills ------------------------------------------------------------------------------------


def test_a_skill_becomes_knowledge_procedures_rules_checks_and_its_files(tmp_path):
    units = _digest(_write(tmp_path / "artifact", RELEASE))
    skill = "skills/release/SKILL.md"
    assert _summary(units) == [
        ("knowledge", "release", skill, 1, 5),
        ("rule", "Never release on a Friday.", skill, 8, 8),
        ("procedure", "Steps", skill, 12, 14),
        ("rule", "Always sign the tag.", skill, 18, 18),
        ("rule", "Do not publish from a dirty tree.", skill, 19, 19),
        ("check", "Verify the wheel installs in a clean virtualenv.", skill, 23, 23),
        ("check", "The changelog names the version.", skill, 24, 24),
        ("script", "skills/release/scripts/build.sh", "skills/release/scripts/build.sh", 1, 2),
        ("example", "skills/release/templates/notes.md", "skills/release/templates/notes.md", 1, 3),
    ]
    knowledge, _, procedure, *_, script, example = units
    assert knowledge.body == "Cut a release of the package.\n\nlicense: MIT"
    assert knowledge.tags == ("skill", "skill:release")
    assert procedure.body == (
        "1. Bump the version in `pyproject.toml`.\n"
        "2. Run `scripts/build.sh` to build the wheel.\n"
        "3. Fill in [the notes template](templates/notes.md)."
    )
    assert script.body == "#!/bin/sh\necho built\n"
    assert "referenced" in script.tags
    assert example.body == "## Notes\n\n- item\n"
    lines = RELEASE[skill].split("\n")
    for unit in (u for u in units[1:7] if u.kind != "procedure"):   # exactly where its words are
        start, end = unit.location.line_start, unit.location.line_end
        assert unit.title in " ".join(" ".join(lines[start - 1:end]).split())


def test_a_folder_of_skills_yields_every_skill(tmp_path):
    units = _digest(_write(tmp_path / "artifact", {**RELEASE, **TRIAGE}))
    assert [u.title for u in units if u.kind == "knowledge"] == ["release", "triage"]
    triage = "skills/triage/SKILL.md"
    assert _summary(units, triage) == [
        ("knowledge", "triage", triage, 1, 6),
        ("procedure", "triage: steps", triage, 7, 9),
        ("rule", "You must link a duplicate when there is one.", triage, 9, 9),
    ]
    assert units[-3].body == "Sort incoming issues by severity."


def test_a_steps_section_of_rules_and_checks_is_still_a_procedure(tmp_path):
    skill = "skills/pin/SKILL.md"
    units = _digest(_write(tmp_path / "artifact", {
        skill: (
            "---\nname: pin\ndescription: Pin dependencies.\n---\n"
            "## Steps\n\n- Always pin dependencies.\n- Verify the result.\n"
        ),
    }))
    assert _summary(units) == [
        ("knowledge", "pin", skill, 1, 4),
        ("procedure", "Steps", skill, 7, 8),
        ("rule", "Always pin dependencies.", skill, 7, 7),
        ("check", "Verify the result.", skill, 8, 8),
    ]
    assert units[1].body == "- Always pin dependencies.\n- Verify the result."


def test_imperative_verification_in_a_skill_is_both_a_rule_and_a_check(tmp_path):
    skill = "skills/gate/SKILL.md"
    units = _digest(_write(tmp_path / "artifact", {
        skill: (
            "---\nname: gate\ndescription: Gate a change.\n---\n"
            "## Steps\n\n1. Make the change.\n2. Verify that you never commit secrets.\n\n"
            "## Verification\n\n- Always run the tests.\n\n"
            "You must run the linter. The diff is reviewed.\n"
        ),
    }))
    assert _summary(units) == [
        ("knowledge", "gate", skill, 1, 4),
        ("procedure", "Steps", skill, 7, 8),
        ("rule", "Verify that you never commit secrets.", skill, 8, 8),
        ("check", "Verify that you never commit secrets.", skill, 8, 8),
        ("rule", "Always run the tests.", skill, 12, 12),
        ("check", "Always run the tests.", skill, 12, 12),
        ("rule", "You must run the linter.", skill, 14, 14),
        ("check", "You must run the linter.", skill, 14, 14),
        ("check", "The diff is reviewed.", skill, 14, 14),
    ]
    assert units[1].body == "1. Make the change.\n2. Verify that you never commit secrets."


def test_verification_after_leading_words_in_a_skill_is_a_check(tmp_path):
    skill = "skills/sums/SKILL.md"
    units = _digest(_write(tmp_path / "artifact", {
        skill: (
            "---\nname: sums\ndescription: Guard the build output.\n---\n"
            "## Build\n\n- Always verify the checksum.\n- After building, verify the signature.\n\n"
            "Always verify the checksum file. After building, confirm the size.\n"
        ),
    }))
    assert _summary(units) == [
        ("knowledge", "sums", skill, 1, 4),
        ("rule", "Always verify the checksum.", skill, 7, 7),
        ("check", "Always verify the checksum.", skill, 7, 7),
        ("check", "After building, verify the signature.", skill, 8, 8),
        ("rule", "Always verify the checksum file.", skill, 10, 10),
        ("check", "Always verify the checksum file.", skill, 10, 10),
        ("check", "After building, confirm the size.", skill, 10, 10),
    ]


def test_prose_in_a_skill_takes_the_kind_of_its_section(tmp_path):
    skill = "skills/notes/SKILL.md"
    units = _digest(_write(tmp_path / "artifact", {
        skill: (
            "---\nname: notes\ndescription: Write release notes.\n---\n"
            "## Rules\n\nSign every tag.\nName every breaking change.\n\n"
            "## Verification\n\nThe changelog names the version. The tag is signed.\n\n"
            "- The changelog names the version.\n"
        ),
    }))
    assert _summary(units) == [
        ("knowledge", "notes", skill, 1, 4),
        ("rule", "Sign every tag.", skill, 7, 7),
        ("rule", "Name every breaking change.", skill, 8, 8),
        ("check", "The changelog names the version.", skill, 12, 12),
        ("check", "The tag is signed.", skill, 12, 12),
        ("check", "The changelog names the version.", skill, 14, 14),
    ]


# --- harness configuration -----------------------------------------------------------------------


def test_harness_configuration_yields_rules_and_procedures(tmp_path):
    units = _digest(_write(tmp_path / "artifact", HARNESS))
    assert _summary(units, "CLAUDE.md") == [
        ("rule", "Always run `make test` before committing.", "CLAUDE.md", 3, 3),
        ("check", "Always run `make test` before committing.", "CLAUDE.md", 3, 3),
        ("procedure", "Workflow", "CLAUDE.md", 7, 9),
        ("check", "Run the tests.", "CLAUDE.md", 9, 9),
        ("rule", "Never force-push to main.", "CLAUDE.md", 13, 13),
    ]
    assert _summary(units, "AGENTS.md") == [
        ("rule", "Do not edit generated files.", "AGENTS.md", 3, 3),
        ("procedure", "Release process", "AGENTS.md", 7, 8),
    ]
    mdc = ".cursor/rules/python.mdc"
    assert _summary(units, mdc) == [
        ("knowledge", "Python style", mdc, 1, 5),
        ("rule", "Always use type hints.", mdc, 6, 6),
    ]
    assert units[0].body == "description: Python style\nglobs: **/*.py\nalwaysApply: false"
    assert _summary(units, ".cursorrules") == [
        ("rule", "Never commit secrets.", ".cursorrules", 1, 1),
    ]
    assert all("harness" in u.tags for u in units)


def test_a_harness_workflow_of_rules_and_checks_is_still_a_procedure(tmp_path):
    units = _digest(_write(tmp_path / "artifact", {
        "CLAUDE.md": (
            "## Workflow\n\n- Always run the linter.\n- Check that the build passes.\n\n"
            "## Verification\n\n- Verify the release notes.\n"
        ),
    }))
    assert _summary(units) == [
        ("procedure", "Workflow", "CLAUDE.md", 3, 4),
        ("rule", "Always run the linter.", "CLAUDE.md", 3, 3),
        ("check", "Always run the linter.", "CLAUDE.md", 3, 3),
        ("check", "Check that the build passes.", "CLAUDE.md", 4, 4),
        ("check", "Verify the release notes.", "CLAUDE.md", 8, 8),
    ]
    assert units[0].body == "- Always run the linter.\n- Check that the build passes."


def test_imperative_verification_in_harness_configuration_is_both_a_rule_and_a_check(tmp_path):
    units = _digest(_write(tmp_path / "artifact", {
        "CLAUDE.md": (
            "## Checks\n\n- Never skip the tests.\n\n"
            "Always run `ruff check` before committing.\n\n"
            "## Workflow\n\n1. Make the change.\n2. Confirm you never left debug output.\n"
        ),
    }))
    assert _summary(units) == [
        ("rule", "Never skip the tests.", "CLAUDE.md", 3, 3),
        ("check", "Never skip the tests.", "CLAUDE.md", 3, 3),
        ("rule", "Always run `ruff check` before committing.", "CLAUDE.md", 5, 5),
        ("check", "Always run `ruff check` before committing.", "CLAUDE.md", 5, 5),
        ("procedure", "Workflow", "CLAUDE.md", 9, 10),
        ("rule", "Confirm you never left debug output.", "CLAUDE.md", 10, 10),
        ("check", "Confirm you never left debug output.", "CLAUDE.md", 10, 10),
    ]
    assert units[4].body == "1. Make the change.\n2. Confirm you never left debug output."
    assert all("harness" in u.tags for u in units)


def test_verification_after_leading_words_in_harness_configuration_is_a_check(tmp_path):
    units = _digest(_write(tmp_path / "artifact", {
        "CLAUDE.md": (
            "## Release\n\n- Always verify the checksum.\n- After building, verify the signature.\n\n"
            "Always verify the checksum file. After building, confirm the size.\n"
        ),
    }))
    assert _summary(units) == [
        ("rule", "Always verify the checksum.", "CLAUDE.md", 3, 3),
        ("check", "Always verify the checksum.", "CLAUDE.md", 3, 3),
        ("check", "After building, verify the signature.", "CLAUDE.md", 4, 4),
        ("rule", "Always verify the checksum file.", "CLAUDE.md", 6, 6),
        ("check", "Always verify the checksum file.", "CLAUDE.md", 6, 6),
        ("check", "After building, confirm the size.", "CLAUDE.md", 6, 6),
    ]


def test_prose_in_harness_configuration_takes_the_kind_of_its_section(tmp_path):
    units = _digest(_write(tmp_path / "artifact", {
        "AGENTS.md": (
            "## Rules\n\nKeep commits small.\n\n"
            "## Verification\n\nThe changelog names the version.\n\n"
            "- The changelog names the version.\n"
        ),
    }))
    assert _summary(units) == [
        ("rule", "Keep commits small.", "AGENTS.md", 3, 3),
        ("check", "The changelog names the version.", "AGENTS.md", 7, 7),
        ("check", "The changelog names the version.", "AGENTS.md", 9, 9),
    ]
    assert all("harness" in u.tags for u in units)


# --- prompt libraries ------------------------------------------------------------------------------


def test_prompt_libraries_yield_one_example_per_prompt(tmp_path):
    units = _digest(_write(tmp_path / "artifact", PROMPTS))
    library = "prompts/library.md"
    assert _summary(units, library) == [
        ("example", "Summarise", library, 5, 5),
        ("example", "Translate", library, 9, 10),
    ]
    assert [u.body for u in units if u.location.path == library] == [
        "Summarise the text below in three bullet points.",
        "Translate the text below into French.\nKeep the tone.",
    ]
    assert _summary(units, "prompts.json") == [
        ("example", "haiku", "prompts.json", 2, 2),
        ("example", "Explain {concept} to a child.", "prompts.json", 3, 3),
        ("knowledge", "Unparsed: prompts.json", "prompts.json", 4, 4),     # no prompt text
    ]
    assert _summary(units, "prompts/roles.json") == [
        ("example", "critic", "prompts/roles.json", 3, 3),
        ("example", "editor", "prompts/roles.json", 4, 6),
    ]
    assert _summary(units, "prompts/chat.jsonl") == [
        ("example", "Linux terminal", "prompts/chat.jsonl", 1, 1),
        ("knowledge", "Unparsed: prompts/chat.jsonl", "prompts/chat.jsonl", 2, 2),
        ("example", "Plain prompt.", "prompts/chat.jsonl", 3, 3),
    ]
    assert _summary(units, "system.prompt") == [
        ("example", "You are a careful reviewer.", "system.prompt", 1, 1),
        ("example", "Second prompt here.", "system.prompt", 3, 3),
    ]
    command = ".claude/commands/review.md"
    assert _summary(units, command) == [("example", "/review", command, 4, 6)]
    assert [u.body for u in units if u.location.path == command] == [
        "# Review\n\nReview the diff for bugs."
    ]
    assert [u.kind for u in _unparsed(units, "prompts/extra.yaml")] == ["knowledge"]
    assert {u.kind for u in units} == {"example", "knowledge"}


# --- determinism ---------------------------------------------------------------------------------


def test_the_same_artifact_gives_the_same_units(tmp_path):
    first = _digest(_everything(tmp_path / "one"))
    assert first == _digest(tmp_path / "one")
    files = {**RELEASE, **TRIAGE, **HARNESS, **PROMPTS}
    _write(tmp_path / "two", dict(reversed(list(files.items()))))     # made in another order
    assert [u.to_dict() for u in _digest(tmp_path / "two")] == [u.to_dict() for u in first]

    assert all(isinstance(u, Unit) and u.kind in UNIT_KINDS for u in first)
    assert all(Unit.from_dict(u.to_dict()) == u for u in first)
    artifact = Artifact(source=SOURCE, kinds=("skill_collection", "configuration"), units=tuple(first))
    assert len(artifact.units) == len({u.id for u in first})


# --- bounds --------------------------------------------------------------------------------------


def test_referenced_files_are_bounded_and_never_run(tmp_path):
    big = "x = 1\n" * 20_000
    root = _write(tmp_path / "artifact", {
        "skills/big/SKILL.md": "---\nname: big\ndescription: Big.\n---\n1. Run `big.py`.\n",
        "skills/big/big.py": big,
    })
    [script] = [u for u in _digest(root) if u.kind == "script"]
    assert script.body == big[:MAX_BODY]
    assert "truncated" in script.tags
    assert (script.location.line_start, script.location.line_end) == (1, script.body.count("\n") + 1)


def test_long_documents_are_bounded(tmp_path):
    steps = "".join(f"{n}. Step number {n} is here.\n" for n in range(1, 3001))
    units = _digest(_write(tmp_path / "artifact", {"CLAUDE.md": steps}))
    [procedure] = [u for u in units if u.kind == "procedure"]
    assert len(procedure.body) == MAX_BODY and "truncated" in procedure.tags
    assert (procedure.location.line_start, procedure.location.line_end) == (1, 3000)
    assert all(len(u.body) <= MAX_BODY and len(u.title) <= MAX_TITLE for u in units)


def test_bytes_read_from_a_file_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "MAX_FILE_BYTES", 1000)
    rules = "".join(f"- Never do thing {n:03}.\n" for n in range(200))     # 22 bytes a line
    units = _digest(_write(tmp_path / "artifact", {"CLAUDE.md": rules}))
    assert "1000 bytes" in _unparsed(units, "CLAUDE.md")[0].body
    assert max(u.location.line_end or 0 for u in units) == 46              # 45 lines and a part


def test_files_units_and_references_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "MAX_FILES", 3)
    units = _digest(_write(tmp_path / "files", {f"prompts/p{n}.txt": f"Prompt {n}." for n in range(10)}))
    assert [u.title for u in units if u.kind == "example"] == ["Prompt 0.", "Prompt 1.", "Prompt 2."]
    assert "first 3 files" in _unparsed(units, ".")[0].body
    monkeypatch.undo()

    monkeypatch.setattr(skills, "MAX_UNITS", 5)
    rules = "".join(f"- Never do thing {n}.\n" for n in range(20))
    units = _digest(_write(tmp_path / "units", {"CLAUDE.md": rules}))
    assert len(units) == 5
    assert [u.kind for u in units[:4]] == ["rule"] * 4
    assert units[-1].location.path == "." and units[-1].tags == ("unparsed",)
    monkeypatch.undo()

    monkeypatch.setattr(skills, "MAX_REFERENCES", 2)
    root = _write(tmp_path / "references", {
        "skills/many/SKILL.md": (
            "---\nname: many\ndescription: Many files.\n---\n"
            "- Use `a.py`.\n- Use `b.py`.\n- Use `c.py`.\n- Use `d.py`.\n"
        ),
        **{f"skills/many/{name}.py": f"print({name!r})\n" for name in "abcd"},
    })
    units = _digest(root)
    assert [u.location.path for u in units if u.kind == "script"] == [
        "skills/many/a.py", "skills/many/b.py",
    ]
    [stopped] = _unparsed(units, "skills/many/SKILL.md")
    assert "first 2 referenced files" in stopped.body and stopped.location.line_start == 7


# --- malformed input -----------------------------------------------------------------------------


MALFORMED = {
    "skills/broken/SKILL.md": "---\nname: broken\n- Never reached.\n",
    "skills/badkey/SKILL.md": "---\nthis is not yaml\n---\n- Never stop.\n",
    "skills/noname/SKILL.md": "---\ndescription: d\n---\n",
    "skills/nofront/SKILL.md": "1. Do it.\n",
    "skills/binary/SKILL.md": b"\x00\x01\x02",
    "skills/latin/SKILL.md": "café".encode("latin-1"),
    "skills/links/SKILL.md": (
        "---\nname: links\ndescription: Links that go nowhere.\n---\n"
        "See [the missing script](missing.py).\n"
        "See [a secret](../../../etc/passwd).\n"
        "See [another](/etc/passwd).\n"
        "See [the site](https://example.invalid/page.md) and [a section](#usage).\n"
    ),
    "prompts/bad.json": "{not json",
    "prompts/number.json": "42",
    "prompts/deep.json": "[" * 50_000,
    "AGENTS.md": "---\nname: agents\n",
}


def test_malformed_input_is_said_not_raised(tmp_path):
    units = _digest(_write(tmp_path / "artifact", MALFORMED))

    def reasons(path: str) -> list[str]:
        return [u.body for u in _unparsed(units, path)]

    assert _summary(units, "skills/broken/SKILL.md") == [
        ("knowledge", "Unparsed: skills/broken/SKILL.md", "skills/broken/SKILL.md", 1, 1),
    ]
    assert "never closed" in reasons("skills/broken/SKILL.md")[0]
    assert "not 'key: value'" in reasons("skills/badkey/SKILL.md")[0]
    assert ("rule", "Never stop.", "skills/badkey/SKILL.md", 4, 4) in _summary(units)
    assert "no name" in reasons("skills/noname/SKILL.md")[0]
    assert "no front matter" in reasons("skills/nofront/SKILL.md")[0]
    assert ("procedure", "nofront: steps", "skills/nofront/SKILL.md", 1, 1) in _summary(units)
    assert "binary" in reasons("skills/binary/SKILL.md")[0]
    assert "not UTF-8" in reasons("skills/latin/SKILL.md")[0]
    links = _unparsed(units, "skills/links/SKILL.md")
    assert [u.location.line_start for u in links] == [5, 6, 7]
    assert "not in the artifact" in links[0].body
    assert "outside the artifact" in links[1].body and "absolute" in links[2].body
    assert "not valid JSON" in reasons("prompts/bad.json")[0]
    assert "list or an object" in reasons("prompts/number.json")[0]
    assert "not valid JSON" in reasons("prompts/deep.json")[0]
    assert "never closed" in reasons("AGENTS.md")[0]
    assert all(u.kind == "knowledge" for u in units if "unparsed" in u.tags)


def test_an_artifact_that_is_not_a_directory_is_said_so(tmp_path):
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    for root in (tmp_path / "file.txt", tmp_path / "missing"):
        [unit] = _digest(root)
        assert unit.location.path == "." and unit.tags == ("unparsed",)


def test_links_out_of_the_artifact_are_not_followed(tmp_path):
    outside = _write(tmp_path / "outside", {
        "secret.txt": "the secret\n",
        "SKILL.md": "---\nname: outside\ndescription: Not in the artifact.\n---\n- Never.\n",
    })
    root = _write(tmp_path / "artifact", {
        "skills/linky/SKILL.md": "---\nname: linky\ndescription: Links.\n---\n1. Read `data.txt`.\n",
    })
    try:
        os.symlink(outside / "secret.txt", root / "skills/linky/data.txt")
        (root / "skills/linked").mkdir()
        os.symlink(outside / "SKILL.md", root / "skills/linked/SKILL.md")
        os.symlink(outside, root / "skills/dirlink", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")
    units = _digest(root)
    assert all("the secret" not in u.body and "Not in the artifact" not in u.body for u in units)
    assert "outside" not in [u.title for u in units]
    assert not [u for u in units if u.location.path.startswith("skills/dirlink")]
    [leads_out] = _unparsed(units, "skills/linky/SKILL.md")
    assert "leads out" in leads_out.body and leads_out.location.line_start == 5
    [linked] = _unparsed(units, "skills/linked/SKILL.md")
    assert "not a regular file" in linked.body


def test_garbage_never_raises(tmp_path):
    rng = random.Random(20260926)
    names = [
        "skills/a/SKILL.md", "CLAUDE.md", "AGENTS.md", ".cursor/rules/x.mdc", "prompts.json",
        "prompts/p.jsonl", "prompts/p.md", "system.prompt", ".claude/commands/c.md",
    ]
    tokens = [
        "---", "\n", "# ", "## ", "- ", "1. ", "```", "~~~", "[a](", ")", "x.py", "../", "/", "{",
        "}", "[", "]", '"', ":", ",", "name: ", "description: ", "always ", "never ", "verify ",
        ">", "|", "  ", "\t", "\x00", "é", "\r\n", "\r", "prompts", "#", "%2e%2e/", "\\",
    ]
    for round_ in range(40):
        files: dict[str, str | bytes] = {"skills/a/x.py": "print(1)\n"}
        for name in names:
            if rng.random() < 0.3:
                files[name] = bytes(rng.randrange(256) for _ in range(rng.randrange(200)))
            else:
                files[name] = "".join(rng.choice(tokens) for _ in range(rng.randrange(80)))
        root = _write(tmp_path / f"round{round_}", files)
        units = _digest(root)
        assert units == _digest(root)
        Artifact(source=SOURCE, kinds=("skill_collection",), units=tuple(units))


# --- reading only --------------------------------------------------------------------------------


def test_the_adapter_only_reads(tmp_path):
    root = _everything(tmp_path / "artifact")
    _write(root, {
        "skills/tools/SKILL.md": "---\nname: tools\ndescription: Tools.\n---\n1. Run `python helper_never_imported.py`.\n",
        "skills/tools/helper_never_imported.py": "open('ran', 'w').close()\nraise SystemExit('imported')\n",
    })
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
    units = _digest(root)
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
    assert after == before
    assert "helper_never_imported" not in sys.modules
    helper = [u for u in units if u.location.path == "skills/tools/helper_never_imported.py"]
    assert [u.kind for u in helper] == ["script"]

    tree = ast.parse(Path(skills.__file__).read_text(encoding="utf-8"))
    modules: set[str] = set()
    functions: set[str] = set()     # called by name: builtins
    methods: set[str] = set()       # called as attributes: os.system, Path.write_text, ...
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            functions.add(node.func.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            methods.add(node.func.attr)
        elif isinstance(node, ast.Attribute) and node.attr.startswith("O_"):
            assert node.attr not in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC")
    roots = {module.split(".")[0] for module in modules}
    assert roots <= set(sys.stdlib_module_names) | {"__future__", "app"}   # standard library only
    assert not modules & {"subprocess", "importlib", "runpy", "shutil", "socket", "ctypes",
                          "multiprocessing", "urllib.request", "http.client", "pickle", "tempfile"}
    assert not functions & {"eval", "exec", "compile", "__import__", "open", "breakpoint"}
    assert not methods & {"system", "popen", "spawnv", "execv", "execvp", "remove", "unlink",
                          "rename", "rmdir", "mkdir", "makedirs", "write", "write_text",
                          "write_bytes", "touch", "chmod", "symlink_to", "import_module"}


# --- regressions: structure, text and bounds -------------------------------------------------------


def test_steps_broken_by_fenced_commands_are_one_procedure_with_the_commands(tmp_path):
    skill = "skills/setup/SKILL.md"
    units = _digest(_write(tmp_path / "artifact", {
        skill: (
            "---\nname: setup\ndescription: Set the tool up.\n---\n"      # 1-4
            "## Steps\n\n"                                                   # 5-6
            "1. Install it:\n\n```bash\npip install tool\n```\n\n"          # 7-12
            "2. Run it:\n\n```bash\ntool run\n```\n\n"                      # 13-18
            "3. Done.\n\n"                                                   # 19-20
            "## Notes\n\n- Keep it simple.\n"                                # 21-23
        ),
    }))
    procedures = [u for u in units if u.kind == "procedure"]
    assert _summary(procedures) == [
        ("procedure", "Steps", skill, 7, 19),
        ("procedure", "Notes", skill, 23, 23),
    ]
    steps = procedures[0].body
    assert "pip install tool" in steps and "tool run" in steps
    assert steps.startswith("1. Install it:") and steps.endswith("3. Done.")


def test_a_procedure_ends_with_the_code_after_its_last_step(tmp_path):
    units = _digest(_write(tmp_path / "artifact", {
        "CLAUDE.md": "## Release\n\n1. Tag the release:\n\n```sh\ngit tag v1\n```\n\nThat is all.\n",
    }))
    [procedure] = [u for u in units if u.kind == "procedure"]
    assert (procedure.location.line_start, procedure.location.line_end) == (3, 7)
    assert procedure.body == "1. Tag the release:\n\n```sh\ngit tag v1\n```"


def test_harness_configuration_opening_with_a_divider_keeps_its_rules(tmp_path):
    units = _digest(_write(tmp_path / "artifact", {
        "CLAUDE.md": "---\n\n# Rules\n\n- Never push to main.\n- Always sign commits.\n",
        "AGENTS.md": "---\n\nNever force-push.\n\n---\n\n- Always run the linter.\n",
    }))
    assert ("rule", "Never push to main.", "CLAUDE.md", 5, 5) in _summary(units)
    assert ("rule", "Always sign commits.", "CLAUDE.md", 6, 6) in _summary(units)
    assert ("rule", "Never force-push.", "AGENTS.md", 3, 3) in _summary(units)
    assert ("rule", "Always run the linter.", "AGENTS.md", 7, 7) in _summary(units)
    [claude] = _unparsed(units, "CLAUDE.md")
    assert "never closed" in claude.body and "read as markdown" in claude.body
    [agents] = _unparsed(units, "AGENTS.md")
    assert "not 'key: value'" in agents.body


def test_a_lone_surrogate_escape_costs_one_character_not_the_file(tmp_path):
    units = _digest(_write(tmp_path / "artifact", {
        "prompts.json": '[{"name": "odd", "prompt": "bad \\ud800 one"}, {"name": "fine", "prompt": "good"}]',
        "skills/odd/SKILL.md": '---\nname: "odd\\udc80"\ndescription: Odd.\n---\n- Never stop.\n',
    }))
    assert [u.title for u in units if u.location.path == "prompts.json"] == ["odd", "fine"]
    assert [u.body for u in units if u.location.path == "prompts.json"] == ["bad ? one", "good"]
    assert ("rule", "Never stop.", "skills/odd/SKILL.md", 5, 5) in _summary(units)
    assert not [u for u in units if "could not be read" in u.body]
    for unit in units:
        assert Unit.from_dict(unit.to_dict()) == unit
    Artifact(source=SOURCE, kinds=("skill_collection",), units=tuple(units))


def test_a_lone_carriage_return_ends_a_line(tmp_path):
    units = _digest(_write(tmp_path / "artifact", {
        "CLAUDE.md": b"# Rules\r\r- Never push.\r- Always test.\r",
    }))
    assert _summary(units) == [
        ("rule", "Never push.", "CLAUDE.md", 3, 3),
        ("rule", "Always test.", "CLAUDE.md", 4, 4),
    ]


def test_folders_count_towards_the_walk_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "MAX_ENTRIES", 50, raising=False)   # a bound the walk must have
    root = _write(tmp_path / "artifact", {"CLAUDE.md": "- Never push.\n"})
    for n in range(60):
        (root / "empty" / f"folder{n:02}").mkdir(parents=True)
    units = _digest(root)
    assert ("rule", "Never push.", "CLAUDE.md", 1, 1) in _summary(units)
    [stopped] = _unparsed(units, ".")
    assert "more than 50 names" in stopped.body and "empty" in stopped.body


def test_folders_too_deep_to_enter_are_said(tmp_path):
    deep = "/".join(["d"] * (skills.MAX_DEPTH + 1))
    units = _digest(_write(tmp_path / "artifact", {
        "CLAUDE.md": "- Never push.\n",
        f"{deep}/AGENTS.md": "- Never merge.\n",
    }))
    assert [u.title for u in units if u.kind == "rule"] == ["Never push."]
    [said] = _unparsed(units, ".")
    assert f"more than {skills.MAX_DEPTH} levels" in said.body


def test_an_artifact_that_is_a_link_is_not_followed(tmp_path):
    outside = _write(tmp_path / "outside", {"CLAUDE.md": "- Never reveal the secret.\n"})
    try:
        (tmp_path / "artifact").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")
    [unit] = _digest(tmp_path / "artifact")
    assert unit.location.path == "." and unit.tags == ("unparsed",)
    assert "link" in unit.body


def test_a_folder_swapped_for_a_link_after_it_was_looked_at_is_not_read(tmp_path, monkeypatch):
    outside = _write(tmp_path / "outside", {"CLAUDE.md": "- Never reveal the secret.\n"})
    root = _write(tmp_path / "artifact", {"sub/CLAUDE.md": "- Never push.\n"})
    target = root / "sub" / "CLAUDE.md"

    def swap_after(look):
        def looked(path, *args, **kwargs):
            result = look(path, *args, **kwargs)
            if Path(path) == target and not (root / "sub").is_symlink():
                (root / "sub").rename(root / "sub.looked-at")
                (root / "sub").symlink_to(outside, target_is_directory=True)
            return result
        return looked

    with monkeypatch.context() as patch:
        patch.setattr(os, "lstat", swap_after(os.lstat))
        patch.setattr(Path, "lstat", swap_after(Path.lstat))
        units = _digest(root)

    assert (root / "sub").is_symlink()         # the swap came between the look and the read
    assert all("secret" not in u.body for u in units)
    [refused] = _unparsed(units, "sub/CLAUDE.md")
    assert "not a regular file" in refused.body


def test_a_table_of_prompts_yields_one_example_per_row(tmp_path):
    units = _digest(_write(tmp_path / "artifact", {
        "prompts.csv": (
            '"act","prompt"\n'                                                  # 1
            '"Linux Terminal","I want you to act as a linux terminal."\n'      # 2
            "\n"                                                                # 3
            '"Poet","Write a poem\nabout {topic}."\n'                          # 4-5
            '"Empty",""\n'                                                      # 6
        ),
        "prompts/roles.tsv": "name\ttemplate\nreviewer\tReview the diff.\n",
        "prompts/columns.csv": "a,b\n1,2\n",
        "prompts/broken.csv": 'prompt\n"a"b\n',
    }))
    assert _summary(units, "prompts.csv") == [
        ("example", "Linux Terminal", "prompts.csv", 2, 2),
        ("example", "Poet", "prompts.csv", 4, 5),
        ("knowledge", "Unparsed: prompts.csv", "prompts.csv", 6, 6),
    ]
    assert [u.body for u in units if u.kind == "example" and u.location.path == "prompts.csv"] == [
        "I want you to act as a linux terminal.", "Write a poem\nabout {topic}.",
    ]
    assert _summary(units, "prompts/roles.tsv") == [
        ("example", "reviewer", "prompts/roles.tsv", 2, 2),
    ]
    assert "needs a column" in _unparsed(units, "prompts/columns.csv")[0].body
    assert "cannot be read" in _unparsed(units, "prompts/broken.csv")[0].body
