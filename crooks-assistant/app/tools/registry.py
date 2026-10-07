"""Tool registry and the in-process MCP adapter.

Every capability the assistant has is a ToolSpec in this registry. The Agent SDK is given
`tools=[]` (no built-ins) and exactly one MCP server — the one built here — so the set of
things Claude can do in the running assistant is precisely the set of things registered below.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from app.reads import budget
from app.tools.gate import Tier

MCP_SERVER_NAME = "crooks"

Handler = Callable[..., Awaitable[Any]] | Callable[..., Any]


@dataclass(slots=True, frozen=True)
class WriteSpec:
    """What makes a write tool a write tool.

    The gate stages a mutation-looking tool for the owner only when every field here is
    present: the tool's own handler is the `prepare` step (it reads the current state and
    builds the exact arguments the mutation will use), `observe` re-reads the state so the
    engine can check it before writing and prove it after, `execute` sends the one reviewed
    mutation with the stored arguments, and `present` names the change for the tablet. A
    registration missing any of them is not a write tool; it is a refusal.
    """

    operation: str                      # the ledger's and the card's name for the change
    entity_kind: str                    # "order"
    entity_arg: str                     # the argument carrying the entity id; must be issued
    mutation: str                       # the reviewed mutation document this sends, by name
    observe: Callable[..., Awaitable[Any]]
    execute: Callable[..., Awaitable[Any]]
    present: Callable[..., dict[str, Any]]
    interaction: str = "tap_commit"     # the gesture at the tool's own tier; recomputed at staging
    # What kind of change this is, for the gesture table (app/actions/grammar.py):
    # "reversible" (an undo card follows), "irreversible", or "money" (money leaves, or an
    # order ends). Defaults from `reversible` when not set.
    op_class: str = ""
    reversible: bool = False
    undo: Callable[..., Any] | None = None   # execution args for the reverse, from the forward's
    spoken_success: str = "Done."
    spoken_undo_success: str = "Undone."
    spoken_failure: str = "I couldn't confirm that change."
    spoken_stale: str = "That changed since it was prepared, so I haven't touched it."
    # Proof. By default the re-read must equal `expected_after` exactly, which suits a note.
    # A cancel, an address or a fulfilment cannot say in advance what Shopify will write
    # (a timestamp, a normalised address, a new id), so they prove by predicate:
    # verify(before, observed, execution) -> (ok, note). The note, when there is one, is
    # spoken after the success line ("the refund isn't showing yet").
    verify: Callable[..., tuple[bool, str]] | None = None
    # Some mutations finish later (orderCancel returns a job). `settle(execution, sent)` waits
    # for it, bounded, before the proving read; with it set, an ambiguous send is never
    # written off as "nothing changed" on the strength of one early re-read.
    settle: Callable[..., Awaitable[Any]] | None = None
    # The entity for the card after a proven change: a fuller read than the fingerprint the
    # proof needs. Optional; without it the card shows what `observe` returned.
    entity: Callable[..., Awaitable[Any]] | None = None
    # Contextual risk: the tier this change should carry given what was prepared. May raise
    # the tool's own tier to RED; never lowers it. Optional.
    risk: Callable[..., Any] | None = None
    # The fingerprint keys the precondition holds the entity to. Unset: every key. Set when a
    # fingerprint also carries a courtesy reading (a fulfilment destination) that may fail on
    # its own and must not make the entity look changed.
    precondition_keys: tuple[str, ...] | None = None
    # The service the change is sent to, as the owner is told who refused it ("CROOKS Returns").
    # Empty: Gmail for a Gmail write, Shopify for the rest, as it always was.
    service: str = ""
    # True: when the proof fails, `verify`'s note (the service's own account of what went wrong)
    # is said after the failure line and shown on the card. False, as it always was: it is not.
    says_failure: bool = False

    @property
    def kind(self) -> str:
        return self.op_class or ("reversible" if self.reversible else "irreversible")

    @property
    def complete(self) -> bool:
        return bool(
            self.operation and self.entity_kind and self.entity_arg and self.mutation
            and callable(self.observe) and callable(self.execute) and callable(self.present)
        )


@dataclass(slots=True, frozen=True)
class BatchSpec:
    """What makes a batch tool a batch tool: the write tool each member's proposal is prepared
    by, which kinds of working set it acts on, and its words. A batch tool has no write of
    its own — every mutation is one of the child tool's, staged and proven one by one by the
    action engine (app/actions/batch.py)."""

    operation: str                      # the batch's name on the card and in the ledger
    child_tool: str                     # the registered write tool used for each member
    set_kinds: tuple[str, ...]          # working-set kinds it accepts: ("orders",)
    present: Callable[..., dict[str, Any]]
    verb: str = "Applied to"            # the spoken result: "{verb} 20 of the 23 {noun}."
    noun: str = "items"
    max_members: int = 50
    # The card's preview of what one member gets (an email's text), from the first prepared
    # child. Optional; bounded by the presentation layer.
    preview: Callable[..., dict[str, Any]] | None = None

    @property
    def complete(self) -> bool:
        return bool(self.operation and self.child_tool and self.set_kinds and callable(self.present))


@dataclass(slots=True, frozen=True)
class BatchPlan:
    """What a batch tool's handler returns: for each member of the set, the arguments the
    child write tool is prepared with. Nothing read yet, nothing sent."""

    set_id: str
    child_tool: str
    child_args: Callable[[str], Any]    # member ref → the child's arguments (or an awaitable of them)
    label: str
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    tier: Tier
    handler: Handler
    # Names of arguments carrying an id that must have been issued earlier this session.
    issued_id_args: tuple[str, ...] = field(default=())
    # A tool's own ceiling, when the operator's default is too tight for what it does (a Gmail
    # search is a listing plus a batched fetch plus a credential refresh on a cold start).
    # Still a hard bound; never unlimited.
    timeout_s: float | None = field(default=None)
    # Present only on a write tool. Its handler then prepares a proposal and never mutates.
    write: WriteSpec | None = field(default=None)
    # Present only on a batch tool: its handler returns a BatchPlan and the batch engine
    # prepares one proposal per member through the child write tool. Never both.
    batch: BatchSpec | None = field(default=None)
    # What the model reads of the result, when that is less than what the card is built
    # from: a street address and an image URL are for the screen, not for the voice.
    model_view: Callable[[Any], Any] | None = field(default=None)


class ToolError(RuntimeError):
    """A tool failed in a way the assistant should report honestly, not paper over."""


_REGISTRY: dict[str, ToolSpec] = {}


def tool(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    tier: Tier = Tier.GREEN,
    issued_id_args: tuple[str, ...] = (),
    timeout_s: float | None = None,
    write: WriteSpec | None = None,
    batch: BatchSpec | None = None,
    model_view: Callable[[Any], Any] | None = None,
) -> Callable[[Handler], Handler]:
    """Register a handler as a tool. The decorated function is returned unchanged so it stays
    directly callable from Python — which is how M5–M9 test tools without spending allowance."""

    def decorator(fn: Handler) -> Handler:
        if name in _REGISTRY:
            raise ValueError(f"Tool {name!r} is already registered.")
        _REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            input_schema=input_schema,
            tier=tier,
            handler=fn,
            issued_id_args=issued_id_args,
            timeout_s=timeout_s,
            write=_proving_in_lane_three(write, name) if write is not None else None,
            batch=batch,
            model_view=model_view,
        )
        return fn

    return decorator


# One unit of work per precondition read, numbered. See `_proving_in_lane_three`.
_PROOF_SEQ = [0]


def _proving_in_lane_three(write: WriteSpec, tool: str) -> WriteSpec:
    """A write's precondition, its proof and its card read in lane 3 (app/reads/budget.py).

    `observe` is called twice by the action engine: once before the mutation, to check the
    entity is still what the proposal was prepared against, and once after, to prove what
    happened. Those are the two reads the brief ranks third — above a background job, above
    speculation, and never served from anything held.

    Wrapped here, at registration, rather than at the call sites: the engine calls these
    callables directly, this is the one place every one of them passes through, and a lane
    that had to be entered by each write tool's author is a lane that will be forgotten by
    one of them. `budget.must_be_fresh(PRECONDITION)` is then true for anything these reads
    reach, so app/reads/dedupe.py will not hand them a held answer or join them to a flight
    started for something else.

    Each call gets its OWN unit of work, so the bound is on that proof and not on how many
    changes the conversation has made. A mutation that needs six reads to know what it is
    about is a bug, not a budget.
    """
    wrapped: dict[str, Any] = {}
    for step in ("observe", "settle", "entity"):
        fn = getattr(write, step, None)
        if callable(fn):
            wrapped[step] = _in_lane(fn, f"{tool}:{step}")
    return replace(write, **wrapped) if wrapped else write


def _in_lane(fn: Callable[..., Any], label: str) -> Callable[..., Any]:
    def key() -> str:
        _PROOF_SEQ[0] += 1
        return f"{label}#{_PROOF_SEQ[0]}"

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def run_async(*args: Any, **kwargs: Any) -> Any:
            with budget.using(budget.PRECONDITION, key()):
                return await fn(*args, **kwargs)

        return run_async

    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> Any:
        with budget.using(budget.PRECONDITION, key()):
            return fn(*args, **kwargs)

    return run


def get(name: str) -> ToolSpec:
    spec = _REGISTRY.get(normalise_tool_name(name))
    if spec is None:
        raise KeyError(f"No tool named {name!r}")
    return spec


def all_specs() -> list[ToolSpec]:
    return sorted(_REGISTRY.values(), key=lambda s: s.name)


def names() -> list[str]:
    return sorted(_REGISTRY)


def clear() -> None:
    """Test helper. Never called by the application."""
    _REGISTRY.clear()


def normalise_tool_name(name: str) -> str:
    """Strip the MCP prefix the SDK adds.

    Tool calls arrive as `mcp__crooks__shopify_find_order`, but the gate, the registry and the
    logs all speak in bare names. Classifying a prefixed name against a bare rule table is how
    a permission gate silently stops matching anything.
    """
    prefix = f"mcp__{MCP_SERVER_NAME}__"
    if name.startswith(prefix):
        return name[len(prefix) :]
    if name.startswith("mcp__"):
        # A differently-named server: take the last segment rather than guessing.
        return name.rsplit("__", 1)[-1]
    return name


async def invoke(name: str, args: dict[str, Any], *, timeout_s: float) -> Any:
    """Run a tool handler with a hard timeout. Does NOT consult the gate — callers must have
    cleared the call first. The single entry point for actually executing a handler."""
    spec = get(name)
    if spec.timeout_s is not None:
        timeout_s = spec.timeout_s
    started = time.perf_counter()
    try:
        if inspect.iscoroutinefunction(spec.handler):
            result = await asyncio.wait_for(spec.handler(**args), timeout=timeout_s)
        else:
            result = await asyncio.wait_for(
                asyncio.to_thread(spec.handler, **args), timeout=timeout_s
            )
    except TimeoutError as exc:
        raise ToolError(
            f"{spec.name} did not respond within {timeout_s:.0f} seconds."
        ) from exc
    except TypeError as exc:
        raise ToolError(f"{spec.name} was called with arguments it does not accept: {exc}") from exc
    if isinstance(result, dict):
        result.setdefault("_ms", round((time.perf_counter() - started) * 1000, 1))
    return result


def build_mcp_server(dispatch: Callable[[str, dict[str, Any]], Awaitable[Any]]):
    """Expose the registry to the Agent SDK as an in-process MCP server.

    `dispatch` is the gated execution path from app/tools/dispatch.py — every tool the SDK can
    reach is wired to it, so there is no route from Claude to a handler that skips the gate.
    """
    from claude_agent_sdk import create_sdk_mcp_server
    from claude_agent_sdk import tool as sdk_tool

    sdk_tools = []
    for spec in all_specs():

        def make(spec: ToolSpec = spec):
            @sdk_tool(spec.name, spec.description, spec.input_schema)
            async def _run(args: dict[str, Any]) -> dict[str, Any]:
                payload = await dispatch(spec.name, args)
                return {"content": [{"type": "text", "text": payload}]}

            return _run

        sdk_tools.append(make())

    return create_sdk_mcp_server(name=MCP_SERVER_NAME, version="1.0.0", tools=sdk_tools)
