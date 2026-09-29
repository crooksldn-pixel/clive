"""Round 13's evidence that is settled by the history of the code rather than by running it now.

T7-01 (round 12): the rollback test runs a copy of the objectives store kept in tests/fixtures and
says it is production's own; the reviewer could not see production's source to check. Here it is
checked against the commit production runs, 6a29e310, byte for byte.

R9-D1-D1-03 (round 9): the fast lane deleted in 4411adde left no write with a weaker check,
because it never wrote. Its own source, at the commit before the deletion, says so in code: every
recipe was held read-only at start-up and before each run, and "cancel" and "refund" were words
that sent a sentence out of the lane to the model.

Both read the repository's own history (`git show`); a checkout without that history — a shallow
clone — skips rather than guesses. CI checks out with its full history (.github/workflows).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PRODUCTION = "6a29e31013b0b9e543d90434e14ed65deea1ce30"
BEFORE_THE_LANE_WENT = "4411adde^"


def _at(commit: str, path: str) -> bytes:
    """The file's bytes at that commit, exactly as git holds them."""
    try:
        shown = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=REPO, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"git is not usable here: {type(exc).__name__}")
    if shown.returncode != 0:
        pytest.skip(f"this checkout does not have {commit}:{path}")
    return shown.stdout


def _text(commit: str, path: str) -> str:
    return _at(commit, path).decode("utf-8")


def test_the_rollback_fixture_is_the_store_production_runs_byte_for_byte():
    """T7-01: tests/fixtures/objectives/store_547f652f.py.txt, which tests/test_objective_rollback.py
    loads as "the store production rolls back to", is exactly app/objectives/store.py at 6a29e310."""
    fixture = (REPO / "crooks-assistant" / "tests" / "fixtures" / "objectives" / "store_547f652f.py.txt").read_bytes()
    production = _at(PRODUCTION, "crooks-assistant/app/objectives/store.py")
    assert fixture == production, "the rollback fixture is not the store production runs"


def test_the_fast_lane_that_was_deleted_could_not_write():
    """R9-D1-D1-03: at 4411adde^, every recipe the lane could run was checked read-only when the
    runtime was built and again before each run — a recipe naming a write or bulk tool was a
    crash, not a change — and a sentence with "cancel" or "refund" in it left the lane for the
    model before any recipe was scored."""
    recipes = _text(BEFORE_THE_LANE_WENT, "crooks-assistant/app/fastpath/recipes.py")
    assert "def assert_read_only(" in recipes
    assert "if spec.write is not None or spec.batch is not None:" in recipes
    assert 'the fast lane cannot write")' in recipes
    runtime = _text(BEFORE_THE_LANE_WENT, "crooks-assistant/app/runtime.py")
    assert "recipe_registry.assert_read_only()" in runtime, "checked when the runtime is built"
    runner = _text(BEFORE_THE_LANE_WENT, "crooks-assistant/app/fastpath/runner.py")
    assert "recipe_mod.assert_read_only({recipe.recipe_id: recipe})" in runner, "and again before each run"
    intent = _text(BEFORE_THE_LANE_WENT, "crooks-assistant/app/fastpath/intent.py")
    strong = intent.split("MUTATION_STRONG = frozenset({", 1)[1].split("})", 1)[0]
    for word in ("cancel", "refund", "archive"):
        assert f'"{word}"' in strong, word
