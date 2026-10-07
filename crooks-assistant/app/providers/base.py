"""The Claude provider interface.

Every route to Claude goes through this ABC. MaxAgentSDKProvider is the only implementation
that does anything; AnthropicAPIProvider exists purely so that swapping billing models later
is a class substitution rather than a rewrite. It must never gain a working body without an
explicit decision, because that decision is a decision to start paying per token.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolCall:
    """One tool invocation Claude made during a turn, as observed by the runtime."""

    name: str
    args: dict[str, Any]
    ok: bool = True
    error: str | None = None
    duration_ms: float | None = None
    # The tool's own bounded result, kept only so app/presentation.py can choose what the
    # tablet shows from data rather than from the prose. Never returned to the tablet raw.
    result: dict[str, Any] | None = None
    # Set when the call was a write: it did not run, it was staged. The presentation layer
    # finds the proposal on the session and builds the action card from it.
    proposal_id: str | None = None
    # The id the test-session timeline wrote this call under, when a session was active.
    tool_call_id: str = ""


@dataclass(slots=True)
class TurnResult:
    """The outcome of one user turn."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    session_id: str = ""
    stopped_early: bool = False
    error_kind: str | None = None  # None on success; otherwise a stable machine-readable kind
    # Where the time went, as (step, ms since the turn began): "model" for each model step,
    # "tool:<name>" for each tool call. Empty for providers that do not measure.
    steps: list[tuple[str, float]] = field(default_factory=list)


class ClaudeProvider(ABC):
    """A source of Claude completions with our tools attached."""

    @abstractmethod
    async def start(self) -> None:
        """Open whatever long-lived resource the provider needs. Called once at startup."""

    @abstractmethod
    async def stop(self) -> None:
        """Release resources. Called once at shutdown."""

    @abstractmethod
    async def turn(self, session_id: str, text: str) -> TurnResult:
        """Run one user turn to completion and return the assistant's answer."""

    async def turn_on_branch(self, session_id: str, text: str, *, branch_id: str = "") -> TurnResult:
        """The same turn, addressed to one half of a divided orb. A provider that keeps one
        conversation per half (the SDK provider) runs the halves concurrently; this default
        is the plain single-conversation turn, which is what a test double wants."""
        return await self.turn(session_id, text)

    @abstractmethod
    async def health(self) -> tuple[bool, str]:
        """Return (ok, human-readable detail) for the /health endpoint."""

    @abstractmethod
    async def reset_session(self, session_id: str) -> None:
        """Drop any conversation state held for this session id."""

    async def set_system_prompt(self, prompt: str) -> None:  # noqa: B027 — optional hook
        """Replace the system prompt for all FUTURE conversations. Default: no-op."""

    async def complete(self, system: str, text: str, *, timeout_s: float = 45.0) -> str:
        """[messaging] One answer to one piece of text, outside any conversation and with no tools
        (a translation: app/messaging/translate.py). A provider that cannot raises, and the caller
        says the answer is missing."""
        raise NotImplementedError("this provider has no one-shot completion")

    async def interrupt(self, session_id: str, *, branch_id: str = "") -> bool:
        """Stop the turn in progress for this session — for one half of it when a branch is
        named, if the provider tells halves apart. Default: nothing to stop."""
        return False
