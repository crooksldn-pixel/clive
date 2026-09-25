"""Claude via the Agent SDK on the Max subscription.

Three properties this module exists to guarantee:

1. No pay-as-you-go credential is ever used. The process refuses to boot if ANTHROPIC_API_KEY
   is set, and the OAuth token is injected into the SDK subprocess environment only.
2. Claude has no capability except our tools. `tools=[]` removes every built-in (no filesystem,
   no bash, no web), `setting_sources=[]` stops it inheriting settings, skills or plugins from
   this machine, and exactly one in-process MCP server is registered.
3. The gate sees every call. `permission_mode="dontAsk"` means nothing prompts a human who is
   not there — so a PreToolUse hook, which fires even for auto-approved tools, does the gating.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

from app.providers.base import ClaudeProvider, ToolCall, TurnResult
from app.secrets import keychain
from app.secrets.keychain import SecretMissing
from app.session.models import Session
from app.tools import registry
from app.tools.context import CURRENT_BRANCH
from app.tools.dispatch import dispatch, make_pretooluse_hook
from app.tools.gate import Tier

log = logging.getLogger("crooks.claude")

# How long /cancel waits for the CLI to acknowledge an interrupt before giving up on it.
INTERRUPT_TIMEOUT_S = 5.0
# How many model turns may run at once. Two: one per half of a divided orb. The tablet is
# single-user, so a third would only ever be a queued repeat; and each turn is a `claude`
# subprocess doing real work, on a Mac that is also transcribing and speaking.
MAX_CONCURRENT_TURNS = 2


def conversation_key(session_id: str, branch_id: str = "") -> str:
    """One Claude conversation per half of the orb. A session that has never been divided
    keeps its plain session id, so nothing that only knows the session changes."""
    return f"{session_id}/{branch_id}" if branch_id else str(session_id)


@dataclass
class _Conversation:
    """One `claude` subprocess and the turn, if any, running on it.

    Everything that used to be a field on the provider — the session the turn is for, the
    tool calls it made, the steps it timed, the position it answers — lives here, because two
    halves of the orb now think at the same time and a field on the provider would be shared
    between them: a tool call from the left half filed against the right, a "moved on" check
    that read the wrong question's position, an interrupt that stopped the other one.
    """

    key: str
    session_id: str
    branch_id: str
    client: object
    holder: _Holder
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = field(default_factory=time.time)
    running: bool = False
    # The turn in flight.
    session: Session | None = None
    calls: list[ToolCall] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    steps: list[tuple[str, float]] = field(default_factory=list)
    turn_started: float = 0.0
    turn_epoch: int | None = None
    # The branch's instruction sequence when this turn began (app/session/branch.py). A new
    # instruction to THIS half moves it; one to the other half does not — which is the whole
    # difference between a divided orb and a queue.
    turn_seq: int | None = None

    def begin(self, session: Session | None) -> None:
        self.session = session
        self.calls = []
        self.states = []
        self.steps = []
        self.turn_started = time.perf_counter()
        self.turn_epoch = session.epoch if session is not None else None
        branch = self.branch()
        self.turn_seq = int(getattr(branch, "instruction_seq", 0) or 0) if branch is not None else None
        self.running = True

    def branch(self):
        if self.session is None or not self.branch_id:
            return None
        return (getattr(self.session, "branches", None) or {}).get(self.branch_id)

    def moved_on(self) -> bool:
        """Whether the owner has replaced the question this turn is answering."""
        if self.session is None:
            return False
        branch = self.branch()
        if branch is not None and self.turn_seq is not None:
            return int(getattr(branch, "instruction_seq", 0) or 0) != self.turn_seq or bool(getattr(branch, "abandoned", False))
        return self.turn_epoch is not None and self.session.epoch != self.turn_epoch

    def step(self, name: str) -> None:
        if self.turn_started:
            self.steps.append((name, round((time.perf_counter() - self.turn_started) * 1000, 1)))


@dataclass
class _Holder:
    """What a client's tool server and hook look through to find their conversation. A client
    is connected before it has one — the pre-warmed spare — so the binding is a slot, filled
    when a conversation adopts the client and emptied when it lets it go."""

    conversation: _Conversation | None = None

    def current_session(self) -> Session | None:
        conv = self.conversation
        return conv.session if conv is not None and conv.running else None


# Every route by which the claude CLI could bill somewhere other than the subscription: a raw
# key, a bearer token, a key-helper script, or a cloud provider. Any of them set means stop.
PAYG_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY_HELPER",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


class BillingGuardError(RuntimeError):
    """A pay-as-you-go credential is present. Refuse to run rather than spend money silently."""


def assert_no_payg_credentials() -> None:
    """Called at startup. The single most expensive mistake this project could make is to fall
    back to API billing without noticing, and the SDK will happily do that if a key is exported."""
    for name in PAYG_ENV_VARS:
        if os.environ.get(name):
            raise BillingGuardError(
                f"{name} is set in this environment. The assistant runs on the Claude Max "
                f"subscription and must never consume pay-as-you-go credit. Unset it (check "
                f"your shell profile) and start again. Do not remove this check."
            )


def withheld_tools(specs, *, writes_enabled: bool) -> set[str]:
    """The tools the model is never offered: a RED read, every write while writes are off,
    and the diagnostic mocks, which exist for the test suite and cost schema bytes on every
    turn. Pure, so the rule can be checked without an SDK."""
    return {
        s.name for s in specs
        if (s.write is None and s.batch is None and s.tier is Tier.RED)
        or ((s.write is not None or s.batch is not None) and not writes_enabled)
        or s.name.startswith("mock_")
    }


class MaxAgentSDKProvider(ClaudeProvider):
    def __init__(
        self,
        *,
        system_prompt: str,
        model: str = "sonnet",
        session_lookup=None,
        tool_timeout_s: float = 8.0,
        cli_path: str = "",
        max_turns: int = 12,
        turn_timeout_s: float = 120.0,
        client_idle_timeout_s: float = 1800.0,
        writes_enabled: bool = False,
        max_concurrent_turns: int = MAX_CONCURRENT_TURNS,
        withheld_by_family=None,
    ) -> None:
        self._system_prompt = system_prompt
        # Off: the write tools are not offered to the model at all, and are disallowed at the
        # SDK layer as well, so the assistant is the read-only one it always was.
        self._writes_enabled = writes_enabled
        # The tools of a capability family the store cannot use right now — a scope not
        # granted, a feature the store does not have, a provider not connected — named by
        # the runtime from the family table (app/capabilities/families.py). A callable, read
        # when a client connects: the model is not offered a tool that can only refuse.
        self._withheld_by_family = withheld_by_family
        self._model = model
        self._session_lookup = session_lookup
        self._tool_timeout_s = tool_timeout_s
        self._cli_path = cli_path
        self._max_turns = max_turns
        self._turn_timeout_s = turn_timeout_s
        self._client_idle_timeout_s = client_idle_timeout_s
        # One `claude` subprocess per conversation, and one conversation per half of the orb
        # (conversation_key). Each carries its own turn state — see _Conversation for why.
        self._conversations: dict[str, _Conversation] = {}
        # One client connected ahead of the next new conversation. Spawning the `claude`
        # subprocess and its MCP handshake is one to three seconds; paying it on the first
        # question of the day, or after "new conversation", is the pause that reads as slow.
        self._spare: object | None = None
        self._spare_holder: _Holder | None = None
        self._spare_task: asyncio.Task | None = None
        self._sweep_task: asyncio.Task | None = None
        self._started = False
        self._auth_mode = "token"  # "token" (a stored setup-token) or "cli" (the CLI's own login)
        # Turns on ONE conversation run one at a time (its lock); turns on different halves
        # run together, up to this many. The mutation boundary is untouched by any of it: a
        # proposal is staged and committed by the action engine, which serialises on its own
        # terms and never lets a background half commit (app/actions/engine.py).
        self._max_concurrent_turns = max(1, int(max_concurrent_turns))
        self._slots = asyncio.Semaphore(self._max_concurrent_turns)

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        assert_no_payg_credentials()
        # The SDK otherwise spawns `claude -v` before every connect and pre-warm: a Node
        # start-up (200-2000 ms) to learn a version this process pins itself.
        os.environ.setdefault("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
        cli = self._resolve_cli()
        if not cli:
            raise RuntimeError(
                "The `claude` CLI is not on PATH. Under uvicorn the PATH differs from your "
                "shell — set CROOKS_CLAUDE_CLI_PATH to its absolute path."
            )
        try:
            keychain.get("claude_oauth_token")
            self._auth_mode = "token"
        except SecretMissing as exc:
            # The CLI keeps its own login, in the login Keychain. That is the normal way this
            # runs: it works from a Terminal and from the login-time LaunchAgents `make
            # install` sets up, because both live in the user's session. It would not work
            # from a system daemon, which nothing here uses.
            if not cli_logged_in(cli):
                raise RuntimeError(
                    f"{exc} (and the claude CLI is not logged in either — run `claude`, then `/login`)."
                ) from exc
            self._auth_mode = "cli"
            log.info(
                "No claude_oauth_token in the Keychain; using the claude CLI's own login "
                "(auth=cli). This needs the claude CLI to be signed in for the account the "
                "assistant runs as."
            )
        self._started = True
        log.info("Claude provider ready (model=%s, auth=%s)", self._model, self._auth_mode)
        self._prewarm_soon()

    async def stop(self) -> None:
        self._started = False   # first, so reset_session does not pre-warm a replacement
        for key in list(self._conversations):
            await self._drop_conversation(key)
        await self._drop_spare()

    # ------------------------------------------------------------ pre-warming

    def _prewarm_soon(self) -> None:
        """Connect the next conversation's client in the background, if none is waiting."""
        if not self._started or self._spare is not None:
            return
        if self._spare_task is not None and not self._spare_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._spare_task = loop.create_task(self._prewarm())

    async def _prewarm(self) -> None:
        from claude_agent_sdk import ClaudeSDKClient

        holder = _Holder()
        try:
            client = ClaudeSDKClient(options=self._options(holder))
            await client.connect()
            await self._verify_auth_source(client)
        except BillingGuardError:
            # Cannot be raised from a background task to anyone; the next real connect will
            # raise it where it stops a turn. Say it loudly here as well.
            log.critical("pre-warmed claude client is billing an API key; dropped it")
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("could not pre-warm a Claude client: %s", exc)
            return
        if self._started and self._spare is None:
            self._spare, self._spare_holder = client, holder
        else:
            await _disconnect_quietly(client)

    async def _drop_spare(self) -> None:
        task, self._spare_task = self._spare_task, None
        if task is not None and not task.done():
            task.cancel()
        spare, self._spare, self._spare_holder = self._spare, None, None
        if spare is not None:
            await _disconnect_quietly(spare)

    def _resolve_cli(self) -> str:
        if self._cli_path:
            return self._cli_path if os.path.exists(self._cli_path) else ""
        return shutil.which("claude") or ""

    # -------------------------------------------------------------- options

    def _withheld(self) -> set[str]:
        """Every tool the model is not offered, by the fixed rule and by the store's state."""
        withheld = withheld_tools(registry.all_specs(), writes_enabled=self._writes_enabled)
        if self._withheld_by_family is not None:
            try:
                withheld |= {str(n) for n in (self._withheld_by_family() or ())}
            except Exception as exc:  # noqa: BLE001 — a family probe must never stop a client connecting
                log.warning("family withholding unavailable: %s", exc)
        return withheld

    def _options(self, holder: _Holder | None = None):
        from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

        holder = holder or _Holder()
        # The tool server and the hook are built per client and look through the holder for
        # the conversation the client belongs to. Bound to the provider instead, every client's
        # tools would report to whichever turn happened to be "current" — wrong the moment two
        # halves of the orb are thinking at once.
        server = registry.build_mcp_server(lambda name, args: self._dispatch(name, args, holder=holder))
        prefix = f"mcp__{registry.MCP_SERVER_NAME}__"
        # Refused twice: disallowed at the SDK layer, and denied by the hook if anything ever
        # reaches it. Belt and braces, because one barrier is one failure away. A RED read
        # never runs; a write is offered only when writes are on, and even then it is only
        # ever staged (app/tools/dispatch.py), never executed by the model's call.
        withheld = self._withheld()
        tool_names = [prefix + n for n in registry.names() if n not in withheld]
        disallowed = [prefix + n for n in sorted(withheld)]

        return ClaudeAgentOptions(
            system_prompt=self._system_prompt,
            model=self._model,
            # No built-in tools. Without this Claude can read and write this machine's files.
            tools=[],
            mcp_servers={registry.MCP_SERVER_NAME: server},
            allowed_tools=tool_names,
            disallowed_tools=disallowed,
            # Nobody is sitting at a terminal to answer a prompt, so nothing may prompt. The
            # gate, not an interactive approval, is what makes this safe.
            permission_mode="dontAsk",
            # Auto-approved tools never reach can_use_tool. The hook fires regardless, which is
            # why the gate lives here and not there.
            hooks={"PreToolUse": [HookMatcher(hooks=[self._hook_for(holder)])]},
            # Do not inherit CLAUDE.md, settings, skills or plugins from this machine.
            setting_sources=[],
            max_turns=self._max_turns,
            cli_path=self._resolve_cli() or None,
            env=(
                {"CLAUDE_CODE_OAUTH_TOKEN": keychain.get("claude_oauth_token")}
                if self._auth_mode == "token"
                else {}
            ),
        )

    def _hook_for(self, holder: _Holder):
        return make_pretooluse_hook(
            holder.current_session,
            on_event=lambda name, tier, disposition="EXECUTE_NOW": self._on_tool_event(name, tier, disposition, holder=holder),
        )

    def _on_tool_event(self, name: str, tier: str, disposition: str = "EXECUTE_NOW", *, holder: _Holder | None = None) -> None:
        conv = holder.conversation if holder is not None else None
        session = conv.session if conv is not None and conv.running else None
        if conv is not None:
            conv.states.append(name)
        denied = disposition == "DENY"
        if denied:
            # A hook-denied call never reaches dispatch, so record it here or the turn log
            # would show a refusal the model reported but no tool call behind it.
            reason = session.refusals[-1].reason if session and session.refusals else "refused"
            call = ToolCall(name=name, args={}, ok=False, error=reason)
            if conv is not None:
                conv.calls.append(call)
            self._trace_refusal(session, call, reason)
        if session is None:
            return
        if denied:
            session.set_state("THINKING", f"refused {name}")
        elif name.startswith("shopify_"):
            session.set_state("CHECKING SHOPIFY", name)
        elif name.startswith("gmail_"):
            session.set_state("CHECKING EMAIL", name)
        else:
            session.set_state("THINKING", name)

    @staticmethod
    def _trace_refusal(session, call: ToolCall, reason: str) -> None:
        """The refusal, on the test-session timeline, in the same two events a dispatched
        call gets — so the report reads both paths alike."""
        from app.observability import timeline

        if timeline.current().active is None:
            return
        call.tool_call_id = timeline.new_id("tc")
        session_id = getattr(session, "session_id", None)
        turn_id = getattr(session, "turn_id", "") or None
        timeline.emit("tool_requested", session_id=session_id, turn_id=turn_id, tool_call_id=call.tool_call_id, tool=call.name, args={}, disposition="DENY", at="hook")
        timeline.emit(
            "tool_finished", session_id=session_id, turn_id=turn_id, tool_call_id=call.tool_call_id, tool=call.name, ok=False,
            outcome="refused", error=str(reason)[:400], ms=0.0, missing_capability=(call.name if "not a registered tool" in reason else None),
        )

    async def _dispatch(self, tool_name: str, args: dict, *, holder: _Holder | None = None) -> str:
        conv = holder.conversation if holder is not None else None
        session = conv.session if conv is not None and conv.running else None
        if session is None or conv is None:
            return "ERROR: no active session for this tool call."
        if conv.moved_on():
            log.info("tool call %s refused: the owner moved on (%s)", tool_name, conv.key)
            return "REFUSED: the owner has moved on to another question. Do not act on this one; answer briefly."
        # Which half this call acts for, on the task the call runs in. The session's own
        # `acting_branch` is one field for both halves and is overwritten by whichever spoke
        # last; with two turns in flight the engine would stamp the left half's proposal with
        # the right half's id. The context variable is per task, so it cannot be.
        token = CURRENT_BRANCH.set(conv.branch_id)
        try:
            return await dispatch(
                tool_name,
                args,
                session=session,
                timeout_s=self._tool_timeout_s,
                calls=conv.calls,
            )
        finally:
            CURRENT_BRANCH.reset(token)
            conv.step(f"tool:{tool_name}")

    # ------------------------------------------------------------------ run

    async def _conversation_for(self, session_id: str, branch_id: str = "") -> _Conversation:
        from claude_agent_sdk import ClaudeSDKClient

        await self._sweep_idle_clients()
        key = conversation_key(session_id, branch_id)
        conv = self._conversations.get(key)
        if conv is None:
            # Held open across turns. Recreating it per request costs seconds of subprocess
            # spin-up and throws away the conversation, which is what makes "and how much did
            # that come to?" work.
            if self._spare is not None:
                client, holder = self._spare, self._spare_holder or _Holder()   # connected and verified already
                self._spare, self._spare_holder = None, None
                log.info("new conversation %s took the pre-warmed client", key)
            else:
                holder = _Holder()
                client = ClaudeSDKClient(options=self._options(holder))
                await client.connect()
                await self._verify_auth_source(client)
            conv = _Conversation(key=key, session_id=str(session_id), branch_id=str(branch_id or ""), client=client, holder=holder)
            holder.conversation = conv
            self._conversations[key] = conv
            self._prewarm_soon()   # and the one after this gets the same head start
        conv.last_used = time.time()
        return conv

    async def _client_for(self, session_id: str, branch_id: str = ""):
        """The client behind a conversation. Kept for the tests and the one caller that only
        wants the subprocess."""
        return (await self._conversation_for(session_id, branch_id)).client

    async def _sweep_idle_clients(self) -> None:
        """Each client is a `claude` subprocess. Sessions expire; their subprocesses must too."""
        now = time.time()
        for key, conv in list(self._conversations.items()):
            if not conv.running and now - conv.last_used > self._client_idle_timeout_s:
                await self._drop_conversation(key)

    async def _drop_conversation(self, key: str) -> None:
        conv = self._conversations.pop(key, None)
        if conv is None:
            return
        conv.holder.conversation = None
        await _disconnect_quietly(conv.client)

    async def _verify_auth_source(self, client) -> None:
        """Ask the running CLI how it authenticated. Belt and braces over the env check: if it
        reports an API key, stop before a single token is billed."""
        try:
            info = await client.get_server_info()
        except Exception:  # noqa: BLE001 — informational; absence is not a failure
            return
        if not isinstance(info, dict):
            return
        # The CLI nests these under `account` (measured: top-level lookups logged '?').
        account = info.get("account") if isinstance(info.get("account"), dict) else {}
        source = str(
            account.get("apiKeySource") or info.get("apiKeySource") or info.get("api_key_source") or ""
        ).lower()
        provider = str(
            account.get("apiProvider") or info.get("apiProvider") or info.get("api_provider") or ""
        ).lower()
        log.info("claude auth source=%r provider=%r", source or "?", provider or "?")
        if source and any(k in source for k in ("api_key", "apikey", "ANTHROPIC_API_KEY".lower())):
            raise BillingGuardError(
                f"The claude CLI reports it is authenticating with an API key ({source}). "
                "That is pay-as-you-go billing. Refusing to continue."
            )

    async def turn(self, session_id: str, text: str) -> TurnResult:
        return await self.turn_on_branch(session_id, text)

    async def turn_on_branch(self, session_id: str, text: str, *, branch_id: str = "") -> TurnResult:
        """One turn, on the conversation that belongs to this half of the orb.

        Two halves think at the same time: each has its own `claude` subprocess, its own lock,
        and its own turn state (_Conversation). What serialises is a turn on the SAME half —
        the second waits for the first, as it always did — and the number of subprocesses
        thinking at once (MAX_CONCURRENT_TURNS). The live test's long turn — thirty-five
        seconds of Claude on one half — no longer holds the other half's two-second question
        behind it.
        """
        if not self._started:
            return TurnResult(
                text="The assistant is still starting up.",
                session_id=session_id,
                error_kind="not_started",
            )
        try:
            conv = await self._conversation_for(session_id, branch_id)
        except Exception as exc:  # noqa: BLE001 — the connect itself can fail (no CLI, billing guard)
            kind, spoken = classify_claude_error(exc)
            log.warning("turn could not connect (%s): %s", kind, exc)
            return TurnResult(text=spoken, session_id=session_id, error_kind=kind)
        async with conv.lock:
            async with self._slots:
                return await self._turn_locked(conv, text)

    async def _turn_locked(self, conv: _Conversation, text: str) -> TurnResult:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

        session_id = conv.session_id
        session = self._session_lookup(session_id) if self._session_lookup else None
        # The conversation position this turn answers. A /cancel or a later question to this
        # half moves it past this turn; a tool call arriving after that acts for nobody and
        # is refused (_Conversation.moved_on).
        conv.begin(session)
        started = conv.turn_started
        if session is not None:
            session.set_state("THINKING")
            session.turns += 1

        result_message = None
        try:
            client = conv.client

            async def run() -> tuple[str, object]:
                await client.query(text)
                parts: list[str] = []
                last = None
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        conv.step("model")
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                parts.append(block.text)
                    elif isinstance(message, ResultMessage):
                        last = message
                        break
                return "\n".join(p.strip() for p in parts if p.strip()).strip(), last

            # A stalled CLI must not hold the turn lock forever.
            answer, result_message = await asyncio.wait_for(run(), timeout=self._turn_timeout_s)
        except TimeoutError:
            log.warning("turn timed out after %.0fs; dropping the client", self._turn_timeout_s)
            await self._drop_conversation(conv.key)
            self._prewarm_soon()
            if session is not None:
                session.set_state("ERROR", "timeout")
            return TurnResult(
                text="That took too long and I have given up on it. Ask me again.",
                tool_calls=conv.calls, session_id=session_id, error_kind="timeout",
            )
        except Exception as exc:  # noqa: BLE001
            kind, spoken = classify_claude_error(exc)
            log.warning("turn failed (%s): %s", kind, exc)
            # A broken client cannot be reused; drop it so the next turn reconnects.
            await self._drop_conversation(conv.key)
            self._prewarm_soon()
            if session is not None:
                session.set_state("ERROR", kind)
            return TurnResult(
                text=spoken, tool_calls=conv.calls, session_id=session_id, error_kind=kind
            )
        finally:
            conv.running = False
            conv.session = None

        # The SDK reports many failures as a ResultMessage rather than an exception — a usage
        # limit, max_turns, an API error. Read it, or a silent failure becomes a blank answer.
        kind = result_kind(result_message)
        if kind is not None:
            spoken = RESULT_SPOKEN.get(kind, RESULT_SPOKEN["unknown"])
            if kind == "usage_limit":
                spoken = usage_limit_line(_result_text(result_message))
            log.warning("turn ended with %s: %s", kind, _result_text(result_message)[:300])
            if kind in {"usage_limit", "auth", "api_error"}:
                await self._drop_conversation(conv.key)
                self._prewarm_soon()
            if session is not None:
                session.set_state("ERROR", kind)
            return TurnResult(
                text=answer or spoken, tool_calls=conv.calls, session_id=session_id,
                error_kind=kind, stopped_early=kind == "max_turns",
            )

        if result_message is not None and getattr(result_message, "permission_denials", None):
            log.info("SDK recorded %d permission denial(s) this turn", len(result_message.permission_denials))

        if session is not None:
            session.set_state("READY")
        # The conversation was used to the end of this turn: its subprocess and its session
        # expire from the same moment, so "that order" cannot be forgotten silently.
        conv.last_used = time.time()
        log.info(
            "turn ok in %.0f ms on %s, %d tool call(s): %s",
            (time.perf_counter() - started) * 1000,
            conv.key,
            len(conv.calls),
            " ".join(f"{name}@{ms:.0f}" for name, ms in conv.steps) or "-",
        )
        return TurnResult(text=answer, tool_calls=conv.calls, session_id=session_id, steps=list(conv.steps))

    async def set_system_prompt(self, prompt: str) -> None:
        """A new knowledge base means a new system prompt, and the SDK fixes the prompt when a
        client connects — so every open client is dropped. The next turn reconnects with the
        new prompt; the conversation history is lost, which is the honest trade."""
        self._system_prompt = prompt
        for key in list(self._conversations):
            await self._drop_conversation(key)
        await self._drop_spare()   # it was connected with the old prompt
        self._prewarm_soon()

    def _running(self, session_id: str, branch_id: str = "") -> list[_Conversation]:
        """The conversations of this session with a turn in flight — one half's when a
        branch is named, every half's when not."""
        return [
            conv for conv in self._conversations.values()
            if conv.running and conv.session_id == str(session_id) and (not branch_id or conv.branch_id == str(branch_id))
        ]

    async def interrupt(self, session_id: str, *, branch_id: str = "") -> bool:
        """Ask the CLI to stop the turn it is running for this session — for this half of it
        when a branch is named, so a cancel on the left never stops the right. The turn then
        ends with whatever text it had, and its lock is released for the question that
        replaced it. True when there was a turn to interrupt."""
        stopped = False
        for conv in self._running(session_id, branch_id):
            try:
                # The SDK's control request would wait a minute on a wedged CLI; the owner's
                # next question is already being asked, and the turn lock is what it waits for.
                await asyncio.wait_for(conv.client.interrupt(), timeout=INTERRUPT_TIMEOUT_S)
            except TimeoutError:
                log.warning("interrupt for %s got no answer in %.0fs", conv.key, INTERRUPT_TIMEOUT_S)
                continue
            except Exception as exc:  # noqa: BLE001 — a turn that already ended is not a failure
                log.info("interrupt for %s did nothing: %s", conv.key, exc)
                continue
            stopped = True
        return stopped

    async def reset_session(self, session_id: str) -> None:
        """Drop every conversation this session holds — each half's."""
        for key, conv in list(self._conversations.items()):
            if conv.session_id == str(session_id):
                await self._drop_conversation(key)
        self._prewarm_soon()   # "new conversation" is about to want one

    async def health(self) -> tuple[bool, str]:
        if not self._started:
            return False, "Claude provider not started."
        if not self._resolve_cli():
            return False, "claude CLI not found on PATH."
        if self._auth_mode == "token":
            try:
                keychain.get("claude_oauth_token")
            except Exception as exc:  # noqa: BLE001
                return False, str(exc)
        note = (
            "" if self._auth_mode == "token"
            else " — the CLI's own login; needs a logged-in claude CLI on the server"
        )
        return True, f"Agent SDK on Max subscription (model={self._model}, auth={self._auth_mode}{note})"

    @property
    def last_tool_states(self) -> list[str]:
        """Tool names touched in the last turn, for the UI's CHECKING SHOPIFY / EMAIL states."""
        return list(self._states)


RESULT_SPOKEN = {
    "usage_limit": (
        "I have hit the Claude usage limit for now. It resets on a rolling five-hour window, "
        "so try again a little later."
    ),
    "max_turns": "That took more steps than I allow myself. Here is as far as I got.",
    "auth": (
        "My Claude login is not working on the server. Run claude there and sign in again with "
        "slash login."
    ),
    "api_error": "Claude returned an error, so I have not got an answer.",
    "unknown": "Something went wrong while I was thinking. I have not got an answer.",
}

_RESET_AT = re.compile(
    r"(?:reset|resets|try again|available)\s*(?:at|in|on)?\s*"
    r"([0-9]+\s*(?:minutes?|mins?|hours?|hrs?)"          # "in 45 minutes"
    r"|[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+Z?"              # ISO timestamp
    r"|[0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)\b(?:\s*\(?[A-Z]{2,4}\)?)?"  # "3pm (UTC)"
    r"|[0-9]{1,2}:[0-9]{2}(?:\s*\(?[A-Z]{2,4}\)?)?)",     # "15:00 UTC"
    re.I,
)


def usage_limit_line(detail: str) -> str:
    """Read the reset time back if the error carries one. No retry loop, ever."""
    match = _RESET_AT.search(detail or "")
    if match:
        when = match.group(1).strip()
        when = when.rstrip(")").replace("(", "")
        joiner = "in" if re.match(r"^\d+\s*(minutes?|mins?|hours?|hrs?)$", when, re.I) else "at"
        when = local_clock(when)
        return f"I have hit the Claude usage limit. It resets {joiner} {when}. I will not retry on my own."
    return RESULT_SPOKEN["usage_limit"]


_UTC_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})\s*(?:UTC|GMT|Z)$", re.I)


def local_clock(when: str) -> str:
    """"15:00 UTC" as the Mac's own clock: "four o'clock" in London in summer. Anything that
    is not a bare UTC time is read out as it came."""
    match = _UTC_CLOCK.match(when.strip())
    if not match:
        return when
    from datetime import UTC, datetime

    hour, minute = int(match.group(1)), int(match.group(2))
    now = datetime.now(UTC)
    local = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0).astimezone()
    return local.strftime("%H:%M")


def _result_text(message) -> str:
    if message is None:
        return ""
    parts = [str(getattr(message, "result", "") or "")]
    errors = getattr(message, "errors", None) or []
    parts.extend(str(e) for e in errors)
    return " ".join(p for p in parts if p)


def result_kind(message) -> str | None:
    """Classify a ResultMessage. None means the turn genuinely succeeded."""
    if message is None:
        return None
    subtype = str(getattr(message, "subtype", "") or "")
    is_error = bool(getattr(message, "is_error", False))
    status = getattr(message, "api_error_status", None)
    text = (subtype + " " + _result_text(message)).lower()
    if not is_error and subtype in {"", "success"}:
        return None
    if "max_turns" in subtype:
        return "max_turns"
    if status == 429 or "usage limit" in text or "rate limit" in text or "rate_limit" in text:
        return "usage_limit"
    if status in (401, 403) or "oauth" in text or "unauthorized" in text or "authentication" in text:
        return "auth"
    if status is not None and status >= 400:
        return "api_error"
    return "unknown" if is_error else None


async def _disconnect_quietly(client) -> None:
    try:
        await client.disconnect()
    except Exception:  # noqa: BLE001 — the subprocess may already be gone
        pass


def cli_logged_in(cli_path: str) -> bool:
    """Ask the CLI itself whether it holds a login. Never reads or prints the credential."""
    try:
        out = subprocess.run(
            [cli_path, "auth", "status"], capture_output=True, text=True, timeout=20
        )
        payload = json.loads(out.stdout or "{}")
        return bool(payload.get("loggedIn"))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def classify_claude_error(exc: Exception) -> tuple[str, str]:
    """Map an SDK failure to a stable kind and the line the assistant should actually say."""
    try:
        from claude_agent_sdk import CLIConnectionError, CLINotFoundError, ProcessError
    except ImportError:  # pragma: no cover
        CLIConnectionError = CLINotFoundError = ProcessError = ()  # type: ignore[assignment]

    text = f"{type(exc).__name__}: {exc}".lower()

    if isinstance(exc, CLINotFoundError):
        return "cli_missing", "The Claude command line tool is missing, so I cannot think."
    if isinstance(exc, ProcessError):
        stderr = str(getattr(exc, "stderr", "") or "").lower()
        text = f"{text} {stderr}"
    if "usage limit" in text or "rate_limit" in text or "rate limit" in text or "429" in text:
        # Never retry this in a loop — retrying a usage-limit error spends more allowance.
        return "usage_limit", usage_limit_line(text)
    if "oauth" in text or "401" in text or "unauthorized" in text or "authentication" in text:
        return "auth", (
            "My Claude login is not working. The subscription token may have expired — it "
            "needs renewing with claude setup-token."
        )
    if isinstance(exc, CLIConnectionError) or any(
        w in text for w in ("connection", "network", "dns", "unreachable", "timeout")
    ):
        return "network", "I cannot reach Claude at the moment. It looks like a network problem."
    if "cli" in text or "enoent" in text or "no such file" in text:
        return "cli_missing", "The Claude command line tool is missing, so I cannot think."
    return "unknown", "Something went wrong while I was thinking. I have not got an answer."
