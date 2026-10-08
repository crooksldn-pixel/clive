"""The one model call research needs, on George's Max plan, and a scripted stand-in for tests.

Why this exists: reading a piece of research for its recommendations, and weighing each against
CLIVE's design, is judgement, so a model does it (app/research/review.py). CLIVE has no
pay-as-you-go billing (MAP.md rule 5), so the call goes the way every turn goes: the `claude` CLI
through the Agent SDK, signed in to the Max plan.

What it promises:
- MaxPlanModel refuses to run with an Anthropic API key in the environment, and stops if the CLI
  says it is billing one (the provider's own checks, app/providers/max_agent_sdk.py).
- The model gets no tools at all, inherits no settings, skills or plugins, and answers once: the
  research is data in its prompt, never something it can act on.
- A failure is an error with words (ModelError), never an empty answer passed off as "nothing
  recommended".
- ScriptedModel answers from a fixed list and records every prompt, for tests. Nothing in the
  running app installs it; tests do, with `install`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

log = logging.getLogger("crooks.research")

TIMEOUT_S = 420.0


class ModelError(Exception):
    """The model could not be asked, or did not answer, said in words."""


class MaxPlanModel:
    """One question to Claude through the claude CLI on the Max plan, with no tools."""

    name = "max-plan"

    def __init__(self, *, model: str = "", cli_path: str = "", timeout_s: float = TIMEOUT_S) -> None:
        self._model = model
        self._cli_path = cli_path
        self._timeout_s = timeout_s

    def _settings(self) -> tuple[str, str]:
        if self._model and self._cli_path:
            return self._model, self._cli_path
        from config.settings import get_settings

        settings = get_settings()
        return self._model or settings.claude_model, self._cli_path or settings.claude_cli_path

    async def ask(self, system: str, prompt: str) -> str:
        from app.providers.max_agent_sdk import (
            BillingGuardError,
            assert_no_payg_credentials,
            classify_claude_error,
            result_kind,
        )

        assert_no_payg_credentials()
        try:
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                ClaudeSDKClient,
                ResultMessage,
                TextBlock,
            )
        except ImportError:
            raise ModelError("The Claude Agent SDK isn't installed on this server.") from None
        model, cli = self._settings()
        options = ClaudeAgentOptions(
            system_prompt=system, model=model or None, tools=[], allowed_tools=[], mcp_servers={},
            permission_mode="dontAsk", setting_sources=[], max_turns=1, cli_path=cli or None,
            env=_token_env(),
        )
        client = ClaudeSDKClient(options=options)
        parts: list[str] = []
        result = None
        try:
            await asyncio.wait_for(client.connect(), timeout=60)
            await _refuse_api_key(client, BillingGuardError)

            async def run():
                await client.query(prompt)
                last = None
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        parts.extend(b.text for b in message.content if isinstance(b, TextBlock))
                    elif isinstance(message, ResultMessage):
                        last = message
                        break
                return last

            result = await asyncio.wait_for(run(), timeout=self._timeout_s)
        except BillingGuardError:
            raise
        except TimeoutError:
            raise ModelError(f"Claude didn't finish reading it within {int(self._timeout_s // 60)} minutes.") from None
        except Exception as exc:  # noqa: BLE001 - every failure is said, never swallowed
            _kind, spoken = classify_claude_error(exc)
            raise ModelError(spoken) from None
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - the subprocess may already be gone
                pass
        kind = result_kind(result)
        if kind is not None:
            raise ModelError(f"Claude stopped before answering ({kind.replace('_', ' ')}).")
        text = "\n".join(p for p in parts if p.strip()).strip()
        if not text:
            raise ModelError("Claude gave no answer.")
        return text


def _token_env() -> dict[str, str]:
    """The stored Max-plan token for the CLI's environment, as the provider passes it; without one
    the CLI's own login is used."""
    try:
        from app.secrets import keychain

        return {"CLAUDE_CODE_OAUTH_TOKEN": keychain.get("claude_oauth_token")}
    except Exception:  # noqa: BLE001 - no stored token: the CLI's own login
        return {}


async def _refuse_api_key(client, error_type) -> None:
    """The provider's check, on this client: a CLI that says it bills an API key is stopped."""
    try:
        info = await client.get_server_info()
    except Exception:  # noqa: BLE001 - informational; absence is not a failure
        return
    if not isinstance(info, dict):
        return
    account = info.get("account") if isinstance(info.get("account"), dict) else {}
    source = str(account.get("apiKeySource") or info.get("apiKeySource") or "").lower()
    if source and any(k in source for k in ("api_key", "apikey")):
        raise error_type(f"The claude CLI reports it is authenticating with an API key ({source}). Refusing to continue.")


class ScriptedModel:
    """Answers from a list, in order (or from a function of the prompt), and keeps every prompt."""

    name = "scripted"

    def __init__(self, answers: list[str] | Callable[[str, str], str]) -> None:
        self._answers = answers
        self.prompts: list[tuple[str, str]] = []

    async def ask(self, system: str, prompt: str) -> str:
        self.prompts.append((system, prompt))
        if callable(self._answers):
            return self._answers(system, prompt)
        if not self._answers:
            raise ModelError("The scripted model has no answer left.")
        return self._answers.pop(0)


_MODEL = None


def current():
    """The model research asks: the Max plan, unless a test installed another."""
    global _MODEL
    if _MODEL is None:
        _MODEL = MaxPlanModel()
    return _MODEL


def install(model) -> object:
    """Use `model` from now on (tests); returns the one it replaced. None puts the Max plan back."""
    global _MODEL
    previous, _MODEL = _MODEL, model
    return previous
