from __future__ import annotations

from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "web" / "app.js"


def test_v05_removes_user_facing_split_entry_points_but_keeps_internal_branch_support() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "split.textContent = 'Split';" not in source
    assert "splitOrb('gesture')" not in source

    # Internal/legacy branch mechanics still exist so concurrency has not been deleted;
    # V0.5 changes who manages it, not whether the runtime can represent it.
    assert "async function splitOrb(" in source
    assert "if (branches.length < 2) {" in source
    assert "if (branches.length > 1)" in source


def test_v05_ready_copy_no_longer_frames_clive_as_an_empty_command_prompt() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "READY: ['CLIVE ready', 'Ask, interrupt, or continue']" in source
    assert "READY: ['System ready.', 'What do you need?']" not in source
