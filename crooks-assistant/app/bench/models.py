"""The model the generator and the judge ask: George's Max plan, or a scripted stand-in.

CLIVE's own turns go through its own provider (app/providers/max_agent_sdk.py), unchanged. This is
for the bench's two other questions, "write me test sentences" and "score this answer", which need
no tools and no conversation: one prompt, one answer.

MaxPlanModel asks Claude through the Agent SDK and the claude CLI, exactly as CLIVE does:
- no pay-as-you-go credential, ever: the same guard CLIVE starts with (assert_no_payg_credentials),
  and the same check of how the CLI says it authenticated, before a word is sent;
- the plan's own token if one is stored as `claude_oauth_token` (the bench serves it from a token
  file, as the build loop's workers are given theirs), otherwise the CLI's own login on this host;
- no tools, no MCP server, no settings, skills or plugins inherited from the machine, one turn.
A usage limit is reported as one, and nothing here retries it: retrying spends more of the plan.

ScriptedModel answers from a function, for the tests and for a dry run that asks no model at all.
Its answers are never presented as a model's: every completion carries the label of what made it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger("crooks.bench.models")

SCRIPTED = "scripted"


@dataclass
class Completion:
    text: str
    model: str                 # what answered: a model id, "scripted", or the alias asked for
    error: str = ""            # why there is no answer, in words
    kind: str = ""             # usage_limit | auth | api_error | timeout | unknown, when it failed

    @property
    def ok(self) -> bool:
        return not self.error


class Model(Protocol):
    label: str

    async def complete(self, *, purpose: str, system: str, prompt: str, context: dict[str, Any]) -> Completion: ...


class UsageLimit(RuntimeError):
    """The plan's limit was reached. The run stops; nothing retries."""


class MaxPlanModel:
    """One prompt, one answer, on the Max plan through the claude CLI."""

    def __init__(self, *, model: str = "sonnet", cli_path: str = "", timeout_s: float = 180.0) -> None:
        self.model = model
        self.cli_path = cli_path
        self.timeout_s = timeout_s
        self.label = f"max:{model}"
        self.resolved: str = ""   # the model id the CLI reported answering with

    def _cli(self) -> str:
        import os
        import shutil

        if self.cli_path:
            return self.cli_path if os.path.exists(self.cli_path) else ""
        return shutil.which("claude") or ""

    def _auth_env(self, cli: str) -> dict[str, str]:
        """The plan's token for the CLI's environment, or nothing when the CLI's own login is used.
        Never read for anything else, never logged."""
        from app.providers.max_agent_sdk import cli_logged_in
        from app.secrets import keychain

        token = keychain.get_optional("claude_oauth_token")
        if token:
            return {"CLAUDE_CODE_OAUTH_TOKEN": token}
        if not cli_logged_in(cli):
            raise RuntimeError("no Max-plan login: the claude CLI is not signed in here and no token file was given")
        return {}

    def options(self, system: str):
        from claude_agent_sdk import ClaudeAgentOptions

        cli = self._cli()
        if not cli:
            raise RuntimeError("the claude CLI is not on PATH (or --cli-path is wrong)")
        return ClaudeAgentOptions(
            system_prompt=system,
            model=self.model,
            tools=[],                 # no filesystem, no shell, no web
            mcp_servers={},
            strict_mcp_config=True,   # and no MCP server from this machine's configuration
            allowed_tools=[],
            permission_mode="dontAsk",
            setting_sources=[],       # no CLAUDE.md, settings, skills or plugins from this machine
            max_turns=1,
            cli_path=cli,
            env=self._auth_env(cli),
        )

    async def complete(self, *, purpose: str, system: str, prompt: str, context: dict[str, Any]) -> Completion:
        from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, TextBlock

        from app.providers.max_agent_sdk import (
            BillingGuardError,
            MaxAgentSDKProvider,
            assert_no_payg_credentials,
            classify_claude_error,
            result_kind,
        )

        assert_no_payg_credentials()
        client = None
        try:
            client = ClaudeSDKClient(options=self.options(system))
            await asyncio.wait_for(client.connect(), timeout=60)
            # The provider's own check of how the CLI authenticated, asked of this client: an API
            # key here stops the call before anything is sent. It does not use the provider's state.
            await MaxAgentSDKProvider._verify_auth_source(None, client)  # type: ignore[arg-type]

            async def ask() -> tuple[str, Any, str]:
                await client.query(prompt)
                parts: list[str] = []
                last, model_id = None, ""
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        model_id = str(getattr(message, "model", "") or model_id)
                        parts.extend(b.text for b in message.content if isinstance(b, TextBlock))
                    elif isinstance(message, ResultMessage):
                        last = message
                        break
                return "\n".join(parts).strip(), last, model_id

            text, result, model_id = await asyncio.wait_for(ask(), timeout=self.timeout_s)
        except BillingGuardError:
            raise
        except TimeoutError:
            return Completion("", self.label, error=f"no answer in {self.timeout_s:.0f}s", kind="timeout")
        except Exception as exc:  # noqa: BLE001 - reported as the failure it is
            kind, _spoken = classify_claude_error(exc)
            return Completion("", self.label, error=f"{type(exc).__name__}: {str(exc)[:300]}", kind=kind)
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001 - the subprocess may already be gone
                    pass
        if model_id:
            self.resolved = model_id
        kind = result_kind(result)
        if kind is not None:
            detail = " ".join(str(x) for x in (getattr(result, "result", "") or "", *(getattr(result, "errors", None) or [])))
            return Completion(text, model_id or self.label, error=f"{kind}: {detail[:300]}".strip(), kind=kind)
        return Completion(text, model_id or self.label)


class ScriptedModel:
    """Answers from `respond(purpose, context)`. For the tests and the dry run; it asks nothing."""

    label = SCRIPTED

    def __init__(self, respond: Callable[[str, dict[str, Any]], str]) -> None:
        self._respond = respond
        self.asked: list[tuple[str, dict[str, Any]]] = []

    async def complete(self, *, purpose: str, system: str, prompt: str, context: dict[str, Any]) -> Completion:
        self.asked.append((purpose, context))
        try:
            return Completion(str(self._respond(purpose, context)), SCRIPTED)
        except Exception as exc:  # noqa: BLE001 - a script that fails is a failed answer, as a model's would be
            return Completion("", SCRIPTED, error=f"{type(exc).__name__}: {exc}", kind="unknown")


def dry_run() -> ScriptedModel:
    """The dry run's stand-in. Generating, it hands back each persona's own example sentences from
    its file, so the questions are words a person wrote and not words made up here. Judging, it says
    it did not judge: a dry run proves the pipeline, and its scores would be fiction."""

    def respond(purpose: str, context: dict[str, Any]) -> str:
        if purpose == "generate":
            persona = context["persona"]
            return json.dumps({"questions": [
                {"category": "example", "turns": [line], "wants": "(the persona file's own example; a dry run asks no model)"}
                for line in persona.examples
            ]})
        if purpose == "judge":
            return json.dumps({"not_judged": "a dry run asks no model, so nothing is scored"})
        raise ValueError(f"the dry run has no answer for {purpose!r}")

    return ScriptedModel(respond)


def parse_json(text: str) -> dict[str, Any] | None:
    """The JSON object in a model's answer: the whole answer, or the outermost braces in it (a
    model may wrap its JSON in a sentence or a code fence). None when there is none."""
    text = str(text or "").strip()
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1] if "{" in text and "}" in text else ""):
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None
