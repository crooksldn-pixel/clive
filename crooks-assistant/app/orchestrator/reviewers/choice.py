"""Which reviewer a loop runs, from its host flags: one place for both loop scripts.

Why it exists: the owner's ruling of 8 October 2026 (DEC-071, ruling 10; DEC-076) made Claude on his plan the
loop's reviewer, and the brief kept GPT selectable so a re-pin can fall back. Both loop scripts
(``engineering_dispatcher.py``, ``remote_engineering.py``) build their reviewers here, so they cannot disagree.

What it promises:

- ``claude`` (the default for a new pin): ``ClaudeCodeReviewer`` takes every new review.
- ``gpt``: the programmatic GPT reviewer exactly as before (``GptUnavailable`` without its key file).
- The reviewer not chosen never takes a new review. It is kept only to finish a review it was given before
  a re-pin switched reviewers (``CollectOnly``), so switching never strands a review in flight: the GPT
  reviewer is kept that way only while the unit still names its key file, the Claude reviewer always.
- ``relay`` stays the engineering dispatcher's courier path, unchanged.
"""

from __future__ import annotations

from pathlib import Path

from .base import ReviewContext
from .claude import ClaudeCodeReviewer
from .gpt import DEFAULT_EFFORT, DEFAULT_MODEL, GptResponsesReviewer
from .relay import GptUnavailable, RelayReviewer

__all__ = ["DEFAULT_REVIEWER", "REVIEWERS", "CollectOnly", "reviewers_for"]

DEFAULT_REVIEWER = "claude"
REVIEWERS = ("claude", "gpt")


class CollectOnly:
    """A reviewer kept only to finish what it was already given: never available for a new dispatch."""

    def __init__(self, driver, chosen: str) -> None:
        self.driver = driver
        self.principal_id = driver.principal_id
        self.mechanism = f"{driver.mechanism} (collect-only)"
        self.courier = driver.courier
        self.reason = (f"collect-only: it finishes reviews dispatched to it before the loop switched to the "
                       f"{chosen} reviewer, and takes no new one")

    def availability(self) -> tuple[bool, str]:
        return False, self.reason

    def start(self, ctx: ReviewContext) -> None:
        self.driver.start(ctx)

    def poll(self, ctx: ReviewContext) -> list[bytes]:
        return self.driver.poll(ctx)

    def problem(self, ctx: ReviewContext) -> str | None:
        return self.driver.problem(ctx) if hasattr(self.driver, "problem") else None

    def exhausted(self, ctx: ReviewContext) -> bool:
        return bool(self.driver.exhausted(ctx)) if hasattr(self.driver, "exhausted") else False


def reviewers_for(choice: str, *, runtime: Path, repo: Path, gpt_key_file: str | None = None,
                  gpt_model: str = DEFAULT_MODEL, gpt_effort: str = DEFAULT_EFFORT, claude_cli: str = "claude",
                  claude_token_file: str | None = None, claude_model: str | None = None,
                  claude_effort: str | None = None, claude_max_turns: int | None = None) -> list:
    """The loop's reviewer drivers, the chosen one first; ``relay`` is the courier path alone."""
    runtime, repo = Path(runtime), Path(repo)
    if choice == "relay":
        return [RelayReviewer(runtime / "relay")]
    claude = ClaudeCodeReviewer(runtime / "claude-review", repo=repo, cli=claude_cli,
                                token_file=Path(claude_token_file) if claude_token_file else None,
                                model=claude_model, effort=claude_effort,
                                **({"max_turns": claude_max_turns} if claude_max_turns else {}))
    gpt = (GptResponsesReviewer(runtime / "gpt", repo=repo, key_file=Path(gpt_key_file), model=gpt_model,
                                effort=gpt_effort) if gpt_key_file else None)
    if choice == "claude":
        return [claude, *([CollectOnly(gpt, "claude")] if gpt is not None else [])]
    if choice == "gpt":
        return [gpt if gpt is not None else GptUnavailable(), CollectOnly(claude, "gpt")]
    raise ValueError(f"unknown reviewer {choice!r}: expected one of {', '.join((*REVIEWERS, 'relay'))}")
