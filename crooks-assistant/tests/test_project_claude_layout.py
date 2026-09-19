"""The project-scoped Claude layout: the parts that exist are checked; the parts that are
pending say so.

`.gitignore` must be in the allowlist form (git cannot re-include a file inside an excluded
directory). `.claude/settings.json`, when present, must register exactly the two reviewed
hooks by project-relative path and nothing else. While it is absent — the worker's permission
layer refused the write, see docs/dev-environment/PROJECT_CLAUDE_FILES_PENDING.md — the
settings test SKIPS with that reason, because a skip that says why is honest and a pass that
checked nothing is not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / ".claude" / "settings.json"
HOOKS = ROOT / "crooks-assistant" / "scripts" / "hooks"


def test_gitignore_lets_versioned_project_config_back_in_by_name() -> None:
    lines = [ln.strip() for ln in (ROOT / ".gitignore").read_text().splitlines()]
    assert ".claude/" not in lines, "a trailing-slash exclusion makes every negation dead"
    assert ".claude/*" in lines
    for allowed in ("!.claude/rules/", "!.claude/skills/", "!.claude/settings.json"):
        assert allowed in lines, allowed
    assert ".claude/settings.local.json" in lines
    assert ".worktrees/" in lines


def test_the_two_hook_scripts_exist_and_are_stdlib_only() -> None:
    for name in ("guard_bash.py", "gitleaks_gate.py"):
        text = (HOOKS / name).read_text(encoding="utf-8")
        assert "#!/usr/bin/env python3" in text.splitlines()[0]
        for third_party in ("import requests", "import yaml", "import httpx", "import click"):
            assert third_party not in text


def test_root_claude_md_is_short_and_points_rather_than_contains() -> None:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) < 60
    assert "docs/DEV_ENVIRONMENT.md" in text
    assert "Never edit, switch or reset `/opt/crooks-os`" in text


@pytest.mark.skipif(
    not SETTINGS.exists(),
    reason=".claude/settings.json is not present — pending the owner's apply step "
    "(docs/dev-environment/PROJECT_CLAUDE_FILES_PENDING.md); this skip proves nothing",
)
def test_settings_register_exactly_the_two_reviewed_hooks() -> None:
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    assert set(data) == {"hooks"}, "only hooks: no permissions, env, model or plugin keys"
    hooks = data["hooks"]
    assert set(hooks) == {"PreToolUse"}
    (entry,) = hooks["PreToolUse"]
    assert entry["matcher"] == "Bash"
    commands = [h["command"] for h in entry["hooks"]]
    assert commands == [
        'python3 "$CLAUDE_PROJECT_DIR/crooks-assistant/scripts/hooks/guard_bash.py"',
        'python3 "$CLAUDE_PROJECT_DIR/crooks-assistant/scripts/hooks/gitleaks_gate.py"',
    ]
    for h in entry["hooks"]:
        assert h["type"] == "command"
        assert 5 <= h["timeout"] <= 180
    for h in entry["hooks"]:
        rel = h["command"].split("$CLAUDE_PROJECT_DIR/", 1)[1].rstrip('"')
        assert (ROOT / rel).is_file(), rel


@pytest.mark.skipif(
    not (ROOT / ".claude" / "skills" / "agent-architecture-audit" / "SKILL.md").exists(),
    reason="vendored skill not present — pending the owner's apply step; this skip proves nothing",
)
def test_vendored_skill_has_narrowed_tools_license_and_provenance() -> None:
    skill = ROOT / ".claude" / "skills" / "agent-architecture-audit"
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert "tools: Read, Grep, Glob\n" in text
    assert "tools: Read, Write, Edit, Bash, Grep, Glob" not in text
    assert (skill / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    prov = (skill / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "07756cee15788a54506031462794ad645719b028" in prov
    assert "64f57e232c3533877403703bc95b3c75df9de23f657899a306f13c703009ff57" in prov
