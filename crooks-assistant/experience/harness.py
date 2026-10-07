"""Driving the assistant the way the tablet drives it, and writing down what came back.

The one rule this file exists to keep: a scenario must go through the same code a person's
voice goes through. `POST /turn` with a `text` body is not a shortcut around the application —
it is the exact point the audio path arrives at once Scribe or whisper has finished, and
everything after it (the affirmation check, the revocation of pending cards, the epoch, the
branch, the model turn, the presenters, the timeline) is shared. So a scenario injects a
transcript there, and nothing here reaches past the HTTP boundary to help it along.

What is swapped is what the Mac talks to: Shopify and Gmail become the golden world, and the
model provider becomes one that records what it was asked and, where the scenario says what
Claude would read for a sentence, calls those tools through the real gate. Those are the same
three seams the runtime itself uses. Nothing else is faked, and in particular no part of the
presentation, gate or action layer is — those are what is being measured.

Timing is recorded in three pieces, because they are three different experiences:

    first useful UI   the turn came back with a surface on it, not a paragraph
    enrichment        the regions that were still loading arrived
    complete          everything, speech included

A turn that answers in 90 ms and shows a card, then finishes the inbox check at 400 ms, is a
good turn. Adding those together and reporting 490 ms describes an experience nobody had.
"""

from __future__ import annotations

import os

# Before anything imports the application. The lifespan warms the order cache at boot, and it
# does so with whatever Shopify client the runtime was built with — which is the real one,
# because the fixture is bound a moment later. That background read went to the real store,
# and awaiting it here hung the harness on the network. Boot does not warm; the harness warms
# once the fixture is in place, and then it is reading the golden world.
os.environ.setdefault("CROOKS_ANALYTICS_WARM_DAYS", "0")

import copy  # noqa: E402
import importlib  # noqa: E402
import time  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402

from app.providers.base import TurnResult  # noqa: E402

# The tablet on the workbench. Everything the harness sends carries these, because a request
# that arrives without them is a request from the Mac itself and takes a different path
# through the allow-list.
OWNER_LOGIN = "owner@example.com"
TABLET_HEADERS = {"Tailscale-User-Login": OWNER_LOGIN, "X-Forwarded-For": "100.64.0.9"}

# What a card that is only bookkeeping looks like. A turn whose entire visible output is the
# context stack has not shown the owner anything he asked for.
BOOKKEEPING = frozenset({"context_stack"})


class RecordingProvider:
    """A model that thinks only as far as a scenario tells it to, and always remembers being asked.

    Every sentence reaches it: nothing on the Mac answers a sentence before the model does
    (app/routes/turn.py). What it does with one is the scenario's to say —
    `h.provider.will("show me order 1938", ("shopify_find_order", {"query": "1938"}), ...)`
    makes the next time it is asked those words call those tools, in order, through the real
    gate as the owner, exactly as Claude's tool calls arrive. So the cards a scenario asserts on
    are drawn by the real presenters from real tool results, and nothing here decides what a
    sentence means. A sentence nobody scripted is answered in a fixed sentence and reads nothing.

    Countable, not absent: a provider that raised would make a model turn look like a crash.
    """

    def __init__(self, reply: str = "[model answer]") -> None:
        self.reply = reply
        self.calls: list[str] = []
        self.runtime: Any = None
        self._scripts: dict[str, tuple[list[tuple[str, dict[str, Any]]], str]] = {}
        # Every scripted call as it was made, its arguments resolved: what `model_could_make`
        # holds to the tool list and the schemas Claude is actually given.
        self.made: list[tuple[str, dict[str, Any]]] = []

    def will(self, said: str, *tools: tuple[str, dict[str, Any]], reply: str = "") -> None:
        """When asked `said`, call `tools` in order and answer `reply`."""
        self._scripts[_key(said)] = (list(tools), reply or self.reply)

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health(self) -> tuple[bool, str]:
        return True, "recording provider"

    async def reset_session(self, session_id: str) -> None: ...
    async def set_system_prompt(self, prompt: str) -> None: ...
    async def interrupt(self, session_id: str) -> bool:
        return True

    async def turn(self, session_id: str, text: str) -> TurnResult:
        self.calls.append(text)
        script = self._scripts.get(_key(said_in(text)))
        if script is None or self.runtime is None:
            return TurnResult(text=self.reply, session_id=session_id)
        from app.tools.dispatch import dispatch

        tools, reply = script
        session = self.runtime.sessions.get_or_create(session_id)
        calls: list[Any] = []
        for name, args in tools:
            # An argument can depend on what an earlier call in the same turn returned — an
            # order_id comes from the search, as it does for Claude — so it may be a function
            # of the calls so far.
            given = args(calls) if callable(args) else args
            self.made.append((str(name), dict(given or {})))
            await dispatch(name, dict(given or {}), session=session, timeout_s=10, calls=calls)
        return TurnResult(text=reply, tool_calls=calls, session_id=session_id)


# The JSON Schema types a tool's arguments are declared in, as Python sees what the model sends.
_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,),
    "array": (list, tuple), "object": (dict,), "null": (type(None),),
}


def _is_json_type(kind: str, value: Any) -> bool:
    """Whether `value` is of the JSON Schema type `kind`. A boolean is never a number, and an
    integer is any number with no fractional part, so 2.0 is one and 2.5 is not: JSON Schema
    says so, and a model's arguments may arrive as either (the 2026-10-01 repair, F-01)."""
    if kind in ("integer", "number") and isinstance(value, bool):
        return False
    if kind == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    return isinstance(value, _JSON_TYPES.get(kind, ()))


def _fits(schema: dict[str, Any], value: Any) -> str:
    """Why `value` is not something this argument's schema admits; empty when it is.

    The whole of the value, not only its outside (the 2026-09-30 deploy review, X1-01): an
    object's own required fields and the types of its fields, every item of an array, a
    number's bounds and a string's length. Checking the top-level type alone passed a line
    item missing its quantity, a list of numbers where the tool takes strings, and a discount
    of 150 per cent, none of which Claude is offered a schema that allows."""
    wanted = schema.get("type")
    kinds = [wanted] if isinstance(wanted, str) else [k for k in (wanted or []) if isinstance(k, str)]
    if kinds:
        ok = any(_is_json_type(k, value) for k in kinds)
        if not ok:
            return f"{type(value).__name__} where the schema says {'/'.join(kinds)}"
    if "enum" in schema and value not in (schema.get("enum") or []):
        return f"{value!r} is not one of {schema.get('enum')}"
    if isinstance(value, str):
        if isinstance(schema.get("maxLength"), int) and len(value) > schema["maxLength"]:
            return f"{len(value)} characters where the schema allows at most {schema['maxLength']}"
        if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
            return f"{len(value)} characters where the schema needs at least {schema['minLength']}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for key, below in (("minimum", True), ("exclusiveMinimum", True), ("maximum", False), ("exclusiveMaximum", False)):
            bound = schema.get(key)
            if not isinstance(bound, (int, float)) or isinstance(bound, bool):
                continue
            exclusive = key.startswith("exclusive")
            outside = (value < bound or (exclusive and value == bound)) if below else (value > bound or (exclusive and value == bound))
            if outside:
                return f"{value!r} is outside the schema's {key} of {bound!r}"
    if isinstance(value, (list, tuple)):
        if isinstance(schema.get("maxItems"), int) and len(value) > schema["maxItems"]:
            return f"{len(value)} items where the schema allows at most {schema['maxItems']}"
        if isinstance(schema.get("minItems"), int) and len(value) < schema["minItems"]:
            return f"{len(value)} items where the schema needs at least {schema['minItems']}"
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                why = _fits(items, item)
                if why:
                    return f"item {index}: {why}"
    if isinstance(value, dict):
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        missing = [key for key in schema.get("required") or [] if key not in value]
        if missing:
            return f"it requires {missing[0]!r}"
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                return f"it has no field {extra[0]!r}"
        for key, item in value.items():
            if isinstance(properties.get(key), dict):
                why = _fits(properties[key], item)
                if why:
                    return f"{key}: {why}"
    return ""


def model_could_make(runtime: Any, name: str, args: dict[str, Any]) -> str:
    """Why Claude could NOT make this call, in words; empty when it could.

    A scripted scenario proves what the gate, the action engine and the presenters do with a
    call — never that Claude would make it (the 2026-09-28 deploy review, round 9, H-02). What
    CAN be held offline is that the call is one Claude is able to make: the tool is on the
    list it is offered on this runtime (not withheld by the fixed rule or by the store's state,
    exactly as `app/providers/max_agent_sdk.py` withholds it), and every argument is one the
    tool's schema declares, with every required one given, and admitted by its schema all the
    way down — the type, an object's required fields, each item of an array, a number's
    bounds and a string's length (`_fits`). A script
    that fails this is scripting something the model cannot do, and the scenario built on it
    proves nothing about a spoken request. Whether Claude WILL choose it is a live question
    this cannot answer.
    """
    from app.providers.max_agent_sdk import withheld_tools
    from app.tools import registry

    try:
        spec = registry.get(name)
    except KeyError:
        return "no tool of that name is registered, so none is offered"
    writes = bool(getattr(getattr(runtime, "settings", None), "writes_enabled", False))
    withheld = withheld_tools(registry.all_specs(), writes_enabled=writes)
    by_family = getattr(runtime, "withheld_by_family", None)
    if callable(by_family):
        withheld |= {str(n) for n in (by_family() or ())}
    if spec.name in withheld:
        return "it is withheld from the model on this runtime"
    schema = spec.input_schema or {}
    properties = schema.get("properties") or {}
    extra = sorted(set(args) - set(properties))
    if extra:
        return f"its schema has no argument {extra[0]!r}"
    missing = [key for key in schema.get("required") or [] if key not in args]
    if missing:
        return f"its schema requires {missing[0]!r}"
    for key, value in args.items():
        why = _fits(properties.get(key) or {}, value)
        if why:
            return f"{key}: {why}"
    return ""


# ------------------------------------------------------------------- what Claude reads for...


def _found_order(calls: list[Any]) -> dict[str, Any]:
    """The order a search in this turn found, as the next call's argument."""
    for call in calls:
        orders = (getattr(call, "result", None) or {}).get("orders") if call.name == "shopify_find_order" else None
        if orders and isinstance(orders[0], dict) and orders[0].get("order_id"):
            return {"order_id": orders[0]["order_id"]}
    return {"order_id": ""}


def order_reads(number: str | int) -> tuple[tuple[str, Any], ...]:
    """...one order, asked for by its number: find it, then read it whole."""
    return (("shopify_find_order", {"query": str(number).lstrip("#")}),
            ("shopify_order_detail", _found_order))


def todays_orders_reads() -> tuple[tuple[str, Any], ...]:
    """...today's orders."""
    return (("shopify_list_orders", {"days": 1}),)


def customer_reads(customer_id: str) -> tuple[tuple[str, Any], ...]:
    """...a customer the conversation has already been shown."""
    return (("shopify_customer_history", {"customer_id": customer_id}),)


def said_in(prompt: str) -> str:
    """The owner's own words in what the model is handed: the line after the clock."""
    lines = str(prompt or "").split("\n")
    return lines[1] if len(lines) > 1 and lines[0].startswith("[Now: ") else str(prompt or "")


def _key(said: str) -> str:
    return " ".join(str(said or "").lower().split())


@dataclass
class Capture:
    """One interaction, and everything that can be said about it without opinion."""

    scenario: str = ""
    kind: str = "voice"                 # voice | touch | touch_then_voice
    command: str = ""
    session_id: str = ""
    branch_id: str = ""
    status: int = 0

    lane: str = ""                      # NORMAL for every sentence, TOUCH for a tap
    recipe_id: str = ""                 # the read a tap named, when it named one
    model_calls: int = 0
    tools: list[str] = field(default_factory=list)
    # The tools the harness's model was TOLD to call for this sentence (`Harness.ask`). Not
    # Claude's choice: what a capture with anything here proves is what the gate, the action
    # engine and the presenters do with those calls — never that the model would make them
    # (the 2026-09-28 deploy review, round 9, H-02). Empty for a tap and an unscripted sentence.
    scripted: list[str] = field(default_factory=list)
    # Scripted calls Claude could not have made, tool -> why (`model_could_make`). Empty for
    # every scenario but the one that reaches for a tool that does not exist on purpose.
    unmakeable: dict[str, str] = field(default_factory=dict)

    answer: str = ""
    ui: list[dict[str, Any]] = field(default_factory=list)
    entity: dict[str, str] | None = None
    set_id: str = ""

    first_ui_ms: float | None = None
    enrichment_ms: float | None = None
    total_ms: float = 0.0

    reads: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------- what it showed

    @property
    def surfaces(self) -> list[dict[str, Any]]:
        """The cards that answered the question, bookkeeping excluded."""
        return [item for item in self.ui if item.get("type") not in BOOKKEEPING]

    @property
    def surface_types(self) -> list[str]:
        return [str(item.get("type") or "") for item in self.surfaces]

    @property
    def prose_only(self) -> bool:
        """The failure this whole pass exists to catch: an answer with nothing to look at."""
        return not self.surfaces

    def surface(self, ui_type: str) -> dict[str, Any] | None:
        for item in self.surfaces:
            if item.get("type") == ui_type:
                return item
        return None

    def data(self, ui_type: str) -> dict[str, Any]:
        item = self.surface(ui_type)
        payload = item.get("data") if isinstance(item, dict) else None
        return payload if isinstance(payload, dict) else {}

    @property
    def actions(self) -> list[dict[str, Any]]:
        """Every action offered anywhere on this turn's cards."""
        out: list[dict[str, Any]] = []
        for item in self.surfaces:
            data = item.get("data")
            if not isinstance(data, dict):
                continue
            for action in data.get("actions") or []:
                if isinstance(action, dict):
                    out.append(action)
            for thread in data.get("threads") or []:
                if isinstance(thread, dict):
                    out.extend(a for a in (thread.get("actions") or []) if isinstance(a, dict))
        return out

    @property
    def action_ids(self) -> list[str]:
        return [str(a.get("operation") or a.get("id") or "") for a in self.actions]

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario, "kind": self.kind, "command": self.command,
            "session_id": self.session_id, "branch_id": self.branch_id, "status": self.status,
            "lane": self.lane, "recipe_id": self.recipe_id,
            "model_calls": self.model_calls, "tools": list(self.tools), "reads": list(self.reads),
            "scripted_model": list(self.scripted),
            "unmakeable": dict(self.unmakeable),
            "answer": self.answer,
            "surfaces": self.surface_types,
            "surface_detail": [
                {"type": i.get("type"), "surface": i.get("surface"),
                 "surface_version": i.get("surface_version"), "entity": i.get("entity"),
                 "linked_entities": i.get("linked_entities"), "loading_regions": i.get("loading_regions")}
                for i in self.surfaces
            ],
            "entity": self.entity, "set_id": self.set_id,
            "actions": self.action_ids,
            "first_ui_ms": self.first_ui_ms, "enrichment_ms": self.enrichment_ms,
            "total_ms": round(self.total_ms, 1),
        }


class Harness:
    """A running assistant, wired to the golden world, that can be spoken to and tapped."""

    def __init__(self, client: httpx.AsyncClient, runtime: Any, provider: RecordingProvider,
                 store: Any, gmail: Any, *, live: bool = False, admitted: bool = False) -> None:
        self.client = client
        self.runtime = runtime
        self.provider = provider
        self.store = store
        self.gmail = gmail
        self.live = live
        # Whether the harness's own requests are let in as the owner's. Off unless a caller asks
        # for it (`harness(admitted=True)`): see `configure`.
        self.admitted = admitted
        self.captures: list[Capture] = []

    # ---------------------------------------------------------------- configuration

    def configure(self, *, writes: bool = True, logins: str = OWNER_LOGIN, admitted: bool | None = None) -> None:
        """Put the backend in the state the tablet meets in production.

        Changes ON and an allow-list naming the owner, because a scenario about which actions a
        card offers proves nothing against a backend where every action is switched off. What
        this does NOT do is make a write possible: the fixture clients refuse every mutation,
        and in live mode the read-only guard refuses it before that.

        Who is let in is the part that differs, and it is chosen, never assumed (the
        2026-09-28 deploy review, round 9, F-A2-FIXTURE). Every harness request carries the
        owner's Tailscale headers, and nothing in this process is tailscaled. So:

            admitted     Tailscale's own confirmation is switched off and the headers are
                         taken as the owner's. Owner scenarios run like this, and every caller
                         that wants it says `harness(admitted=True)` — it is the stand-in for
                         a device Tailscale has vouched for, and it is named as one.
            not          the production identity check, exactly: CROOKS_TAILSCALE_VERIFY on,
                         so the same headers from this process are what they are — a claim
                         nobody confirmed — and every route but the public ones refuses them.
                         This is the harness's default, and `forged_owner_headers` holds it.

        `admitted` left out keeps whichever the harness is in, so a scenario that resets the
        switches does not quietly change who is asking.
        """
        from app.main import app

        if admitted is not None:
            self.admitted = admitted
        self.runtime.settings = self.runtime.settings.model_copy(
            update={"writes_enabled": writes, "allowed_logins": logins,
                    "writes_local_owner": False, "tailscale_verify": not self.admitted}
        )
        app.state.allowed_logins = self.runtime.allowed_logins

    # ---------------------------------------------------------------- speaking

    async def say(self, text: str, *, scenario: str = "", session_id: str = "s1",
                  branch_id: str = "") -> Capture:
        """Inject a transcript where the recogniser hands one over, and record what happened."""
        before_model = len(self.provider.calls)
        before_reads = len(getattr(self.store, "queries", []))
        body: dict[str, Any] = {"text": text, "session_id": session_id}
        if branch_id:
            body["branch_id"] = branch_id
        started = time.perf_counter()
        response = await self.client.post("/turn", json=body, headers=TABLET_HEADERS)
        elapsed = (time.perf_counter() - started) * 1000
        payload = response.json() if response.content else {}
        capture = self._capture(
            scenario=scenario or text, kind="voice", command=text, session_id=session_id,
            response=response, payload=payload, elapsed=elapsed,
            model_calls=len(self.provider.calls) - before_model,
            reads=[q[0] for q in getattr(self.store, "queries", [])[before_reads:]],
        )
        self.captures.append(capture)
        return capture

    async def ask(self, text: str, *tools: tuple[str, Any], reply: str = "", **kwargs: Any) -> Capture:
        """Say `text`, with the model calling `tools` for it through the gate, as Claude would.

        The sentence goes to the model like every sentence; what is scripted is what the model
        then CALLS, so the cards are drawn by the real presenters from real results — and a
        scenario built on this is a scripted gate-and-presenter test, not evidence that Claude
        would choose these tools. The capture says so (`Capture.scripted`), and so does the
        report. What it can say is whether each call is one Claude COULD make on this runtime
        — offered to it, with arguments its schema admits — and a call that is not is named on
        the capture (`Capture.unmakeable`, `model_could_make`).
        """
        self.provider.will(text, *tools, reply=reply)
        before = len(self.provider.made)
        capture = await self.say(text, **kwargs)
        capture.scripted = [str(name) for name, _ in tools]
        for name, args in self.provider.made[before:]:
            why = model_could_make(self.runtime, name, args)
            if why:
                capture.unmakeable[name] = why
        return capture

    async def open_order(self, number: str | int, *, said: str = "", **kwargs: Any) -> Capture:
        """"Show me order N", and the two reads Claude makes for it."""
        number = str(number).lstrip("#")
        return await self.ask(said or f"show me order {number}", *order_reads(number),
                              reply=f"Order {number}.", **kwargs)

    async def list_todays_orders(self, *, said: str = "show me today's orders", **kwargs: Any) -> Capture:
        return await self.ask(said, *todays_orders_reads(), reply="Today's orders.", **kwargs)

    async def customer_history(self, customer_id: str, *, said: str = "what else has this customer ordered?",
                               **kwargs: Any) -> Capture:
        return await self.ask(said, *customer_reads(customer_id), reply="Their history.", **kwargs)

    # ---------------------------------------------------------------- tapping

    async def touch(self, command: str, *, scenario: str = "", session_id: str = "s1",
                    branch_id: str = "", **arguments: Any) -> Capture:
        """A tap, as the tablet sends it: a semantic command and nothing else.

        The tablet never posts what a command should DO — only which command it was and which
        record it was on. What that means is decided here, on the Mac, by the same code a
        spoken instruction reaches.
        """
        before_model = len(self.provider.calls)
        before_reads = len(getattr(self.store, "queries", []))
        form = {"session_id": session_id, "command": command,
                **{k: str(v) for k, v in arguments.items() if v is not None}}
        if branch_id:
            form["branch_id"] = branch_id
        started = time.perf_counter()
        response = await self.client.post("/command", data=form, headers=TABLET_HEADERS)
        elapsed = (time.perf_counter() - started) * 1000
        payload = response.json() if response.content else {}
        capture = self._capture(
            scenario=scenario or command, kind="touch", command=command, session_id=session_id,
            response=response, payload=payload, elapsed=elapsed,
            model_calls=len(self.provider.calls) - before_model,
            reads=[q[0] for q in getattr(self.store, "queries", [])[before_reads:]],
        )
        self.captures.append(capture)
        return capture

    # ---------------------------------------------------------------- enrichment

    async def enrich(self, order_id: str, *, session_id: str = "s1") -> tuple[float, dict[str, Any]]:
        """The regions the turn did not wait for, collected as the tablet collects them."""
        started = time.perf_counter()
        response = await self.client.get(
            f"/context/order/{order_id}", params={"session_id": session_id}, headers=TABLET_HEADERS
        )
        elapsed = (time.perf_counter() - started) * 1000
        return elapsed, (response.json() if response.content else {})

    # ---------------------------------------------------------------- state

    async def state(self, session_id: str = "s1") -> dict[str, Any]:
        response = await self.client.get(f"/state/{session_id}", headers=TABLET_HEADERS)
        return response.json() if response.content else {}

    def branch(self, session_id: str = "s1", branch_id: str = "") -> Any:
        session = self.runtime.sessions.get_or_create(session_id)
        return session.branch(branch_id) if branch_id else session.branch()

    # ---------------------------------------------------------------- capture

    def _capture(self, *, scenario: str, kind: str, command: str, session_id: str,
                 response: httpx.Response, payload: dict[str, Any], elapsed: float,
                 model_calls: int, reads: list[str]) -> Capture:
        ui = [i for i in (payload.get("ui") or []) if isinstance(i, dict)]
        capture = Capture(
            scenario=scenario, kind=kind, command=command, session_id=session_id,
            branch_id=str(payload.get("branch_id") or ""), status=response.status_code,
            lane=str(payload.get("lane") or ""),
            recipe_id=str(payload.get("recipe_id") or (payload.get("changed") or {}).get("recipe_id") or ""),
            model_calls=model_calls, ui=ui, answer=str(payload.get("answer") or ""),
            tools=[str((t or {}).get("name") or "") for t in (payload.get("tools") or []) if isinstance(t, dict)],
            reads=reads, total_ms=elapsed, raw=payload,
        )
        # What the MAC took to have something worth looking at, which is the number the
        # tablet's experience is made of and the only part of it this machine controls. It is
        # the backend's own measure, reported on the turn; `total_ms` is the round trip, which
        # here is ASGI and on the workbench is Wi-Fi.
        #
        # These were the same number until now — `first_ui_ms` was assigned `elapsed`, the same
        # value as `total_ms` — so the report printed one measurement in two columns under a
        # heading saying they were different things, and the scenario check that "first useful
        # UI is measured apart from the whole turn" could not fail. A turn that showed nothing
        # still has no first-UI time: "the paragraph arrived" is not a UI measurement.
        served = payload.get("timings_ms")
        served_total = served.get("total") if isinstance(served, dict) else None
        if served_total is None:
            # A tap: /command reports the whole request as `served_ms` (its `ms` stops before
            # the read a cursor move can cause).
            served_total = payload.get("served_ms")
        capture.first_ui_ms = (
            round(float(served_total), 1) if capture.surfaces and isinstance(served_total, (int, float))
            else (round(elapsed, 1) if capture.surfaces else None)
        )
        # Read, never made: a request the door refused made no conversation, and a capture that
        # created one to look inside it would hide exactly that.
        if not self.runtime.sessions.exists(session_id):
            return capture
        branch = self.branch(session_id, capture.branch_id)
        entity = getattr(branch, "entity", None)
        if isinstance(entity, dict) and entity.get("ref"):
            capture.entity = {"kind": str(entity.get("kind") or ""), "ref": str(entity["ref"]),
                              "label": str(entity.get("label") or "")}
        workflow = getattr(branch, "workflow", None)
        capture.set_id = str(getattr(workflow, "set_id", "") or "") if workflow is not None else ""
        return capture


# What the harness, and the start-up it runs (app/runtime.py `build`), bind into the tool modules
# for the length of a run: the Shopify and Gmail clients the reads and writes use, the order
# cache and inbox helpers the analytics reads use, both write modules' policy — which is the
# harness runtime's settings, changes switched on — and the engineering tools' inbox and the
# interpreter their checks name. Each is put back as it was on the way out. These, with
# `_TOOL_CONFIG` and `_STORE_CONFIG` below, are every `bind` and `configure` call `build` makes
# (tests/test_followups_harness.py reads `build` and holds the three lists to it); the
# process-wide stores it `install`s (the action engine, the objectives, the timeline and the
# rest) are replaced by every runtime that is built and are not bindings of the harness's.
_TOOL_BINDINGS = (
    ("app.tools.shopify_tools", ("_client", "_hydrator")),
    ("app.tools.gmail_tools", ("_client", "_customer_lookup")),
    ("app.tools.gmail_writes", ("_client", "_customer", "_policy")),
    ("app.tools.shopify_writes", ("_policy",)),
    ("app.tools.analytics_tools", ("_cache", "_threads_for", "_replied", "_reply_state", "_own_address",
                                   "_inbox_for", "_sent_for")),
    ("app.tools.engineering_tools", ("_inbox", "_check_python")),
)
# What `build` configures by changing a module's dictionary or list in place rather than rebinding
# a name: the Instagram client's API version and state file (`instagram_tools.configure`), where
# the owner's passkeys and the record of changes to connections are kept
# (`connections_service.configure`), where the team's grants are kept and the cache of them
# (`staff_access.configure`), and the runtime the work list reads the shop and the inboxes through
# (`work_tools.bind`, a one-item list) — the fixture runtime, left there, would outlive the run as
# the housekeeper once did — the address CROOKS Returns is reached at (`crooks_returns.configure`),
# and where the installed skills are read (`skill_tools.configure`).
_TOOL_CONFIG = (
    ("app.clients.instagram", ("_CONFIG", "_STATE")),
    ("app.connections.passkeys", ("_CONFIG",)),
    ("app.connections.ledger", ("_CONFIG",)),
    ("app.people.access", ("_CONFIG", "_CACHE")),
    ("app.work.tools", ("_RUNTIME",)),
    ("app.speech.voice_prefs", ("_CONFIG",)),
    ("app.clients.crooks_returns", ("_SETTINGS",)),
    ("app.tools.skill_tools", ("_CONFIG",)),
    # [loop upgrade, 7 Oct] the build server's private channel the Builds screen reads (engineering_private.configure)
    ("app.engineering_bridge.private", ("_STATE",)),
    # [messaging] who translates a message as it arrives (`messaging_translate.bind`).
    ("app.messaging.translate", ("_COMPLETE",)),
)
# And the stores `build` configures by setting an instance's attributes: (module, the instance's
# name there, its attributes) — the team's cards (`people_store.configure`) and the work list's
# folder (`work_store.configure`).
_STORE_CONFIG = (
    ("app.people.store", "people", ("_path",)),
    ("app.work.store", "work", ("_folder", "_archived_on")),
    # [messaging] the private store of conversations (`messaging_store.configure`).
    ("app.messaging.store", "store", ("_root",)),
)
# A `configure` that `build` calls on one module and that sets another module's configuration:
# the module it calls, and the modules whose configuration `_TOOL_CONFIG` records for it.
CONFIGURED_THROUGH: dict[str, tuple[str, ...]] = {
    "app.tools.instagram_tools": ("app.clients.instagram",),
    "app.connections.service": ("app.connections.passkeys", "app.connections.ledger"),
}


def _tool_bindings() -> dict[tuple[str, str], Any]:
    """What each of `_TOOL_BINDINGS` holds now, a copy of each of `_TOOL_CONFIG`, and the value of
    each attribute `_STORE_CONFIG` names (keyed `instance.attribute`)."""
    bound = {(module, name): getattr(importlib.import_module(module), name)
             for module, names in _TOOL_BINDINGS for name in names}
    bound.update({(module, name): copy.copy(getattr(importlib.import_module(module), name))
                  for module, names in _TOOL_CONFIG for name in names})
    bound.update({(module, f"{instance}.{name}"): getattr(getattr(importlib.import_module(module), instance), name)
                  for module, instance, names in _STORE_CONFIG for name in names})
    return bound


def _put_back(bound: dict[tuple[str, str], Any]) -> None:
    """Every binding and configuration `_tool_bindings` recorded, as it was. A dictionary or list
    is refilled in place, because the module's own functions hold that very object."""
    in_place = {(module, name) for module, names in _TOOL_CONFIG for name in names}
    on_stores = {(module, f"{instance}.{name}") for module, instance, names in _STORE_CONFIG for name in names}
    for (module, name), value in bound.items():
        target = importlib.import_module(module)
        if (module, name) in in_place:
            held = getattr(target, name)
            if isinstance(held, dict):
                held.clear()
                held.update(value)
            else:
                held[:] = value
        elif (module, name) in on_stores:
            instance, attribute = name.split(".", 1)
            setattr(getattr(target, instance), attribute, value)
        else:
            setattr(target, name, value)


@asynccontextmanager
async def harness(*, live: bool = False, writes: bool = True, admitted: bool = False):
    """A running assistant against the golden world, torn down afterwards.

    What it grants, and to what (the 2026-09-28 deploy review, round 9, F-A2-FIXTURE):

    - `writes=True` (the default) switches changes ON in the harness's own runtime, because a
      scenario about which actions a card offers proves nothing against a backend where every
      action is off. Nothing can be applied all the same: the fixture world refuses every
      mutation, and in live mode the read-only guard refuses it first.
    - `admitted=True` lets the harness's own HTTP requests in as the owner's: its runtime's
      allow-list names the fixture owner and Tailscale's confirmation is switched off, so the
      tablet headers it sends are taken as his (`Harness.configure`). The default is the
      production identity check, under which they are refused: a caller that drives owner
      scenarios asks for the owner by name.
    - Tool authority, to nobody directly. Owner authority exists only inside a request the door
      admitted (app/main.py stamps it and revokes it when the answer is sent); the harness
      stamps none on the code that drives it, so a tool called from a scenario's own code, or a
      test's, outside a request is refused like any other.

    And none of it outlives the harness. The application object is shared by the whole process,
    so what this and the lifespan it runs put on it — every attribute of `app.state` (the
    runtime whose switches `configure` sets, the allow-list the door reads, the housekeeper
    made for that runtime), and the fixture clients, write policies and configuration bound
    into the tool modules and the stores (`_TOOL_BINDINGS`, `_TOOL_CONFIG`, `_STORE_CONFIG`) — is
    put back as it was on the way out, whatever happened inside. A test
    that runs after this one meets the app and the tools as it found them, and never the fixture
    owner's allow-list, an unverified Tailscale header or changes switched on.

    `live=True` swaps the golden world for the real Shopify and Gmail credentials and arms the
    read-only guard. It is refused unless the guard is actually in place — see
    `experience/live.py`; a live run that could write is not a test, it is an incident.
    """
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.main import app
    from app.session.manager import SessionManager
    from app.tools import gmail_tools, shopify_tools

    async def fake_scribe_health(_self: Any) -> tuple[bool, str]:
        return True, "harness"

    scribe_health, voice_health = ScribeClient.health, VoiceClient.health
    # Everything the harness or the lifespan it runs changes on the shared app and in the tool
    # modules, as it was before: put back in `finally`. The whole of `app.state`, not a list of
    # names: the lifespan sets the runtime, the allow-list, the health cache and its lock and the
    # housekeeper — which holds the runtime it was made for — and a list kept here would miss
    # whatever the lifespan sets next (the 2026-09-28 deploy review, round 9, F-A2-FIXTURE: the
    # housekeeper was left holding the fixture runtime).
    state_before = dict(_app_state(app))
    bound_before = _tool_bindings()
    ScribeClient.health = fake_scribe_health
    VoiceClient.health = lambda _self: (True, "harness")
    try:
        async with app.router.lifespan_context(app):
            runtime = app.state.runtime
            provider = RecordingProvider()
            provider.runtime = runtime
            runtime.provider = provider
            if live:
                from experience.live import arm_read_only

                store, gmail = arm_read_only(runtime)
            else:
                from app.runtime import _make_customer_lookup
                from app.tools import gmail_writes
                from experience.fixtures import FixtureShopify, data, fixture_gmail

                # The world on the day the application is on, not the day the suite was
                # collected: a run that crosses midnight otherwise asks for today's orders
                # in a world whose today has become yesterday (data.rebase).
                data.rebase()
                store, gmail = FixtureShopify(), fixture_gmail()
                runtime.shopify = store
                shopify_tools.bind(store)
                runtime.gmail = gmail
                # `runtime.customer_lookup` does not exist — production wires the lookup as a
                # closure over the store — so this bound None and the Shopify half of every
                # inbox decision was dead code in every scenario: `known_customer` was None on
                # every thread, and "the automated sender is not offered as a customer" passed
                # only because the fixture's sender matches on its address alone.
                gmail_tools.bind(gmail, customer_lookup=_make_customer_lookup(store))
                # And the WRITE module keeps its own client, bound separately at boot. Left
                # alone, every draft, send and archive in the fixture world went to the client
                # `runtime.build()` made — the real one. Under pytest conftest turns that into
                # an error; `scripts/experience.py` on the Mac has no such net.
                # No `customer=`: the write module's own fallback reads the customer off the
                # order through `shopify_tools.hydrator()`, which is bound to the fixture store
                # two lines up. What was passed here instead was `gmail_tools`' email->bool
                # sender check, and `_order_customer` calls its lookup with TWO arguments — so
                # every gmail_draft_new and gmail_send_new carrying an order_id failed in the
                # fixture world with a TypeError about positional arguments. Found by the
                # composer family, whose scenarios are the first to reach that path.
                gmail_writes.bind(gmail, policy=lambda: runtime.settings)
            runtime.sessions = SessionManager()
            # The order cache, warmed the way boot warms it — but awaited. Production kicks
            # this off in the background and the first question of the day is answered from
            # memory; a scenario that raced it would sometimes ask a cold cache and be told
            # there were no orders today, which is a flaky test dressed up as a bug report.
            await _warm(runtime)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://tablet") as client:
                harness_ = Harness(client, runtime, provider, store, gmail, live=live, admitted=admitted)
                harness_.configure(writes=writes)
                yield harness_
    finally:
        ScribeClient.health = scribe_health
        VoiceClient.health = voice_health
        held = _app_state(app)
        held.clear()
        held.update(state_before)
        _put_back(bound_before)


def _app_state(app: Any) -> dict[str, Any]:
    """The dictionary behind `app.state` (Starlette keeps every attribute set on it there)."""
    return app.state._state


async def _warm(runtime: Any, days: int = 90) -> None:
    """Read the recent window into the order cache and wait for it.

    The cache holds a late-binding callable for its client, so by the time this runs it is
    reading whatever the harness bound. That is checked rather than assumed: a warm that went
    to the real store would be a scenario quietly reading a real shop, which is the one thing
    a fixture run must never do.
    """
    cache = getattr(runtime, "order_cache", None)
    if cache is None:
        return
    client = cache._client()
    if type(client).__name__ not in ("FixtureShopify", "ReadOnlyShopify"):
        raise AssertionError(
            f"the order cache would warm against {type(client).__name__}, which is not the "
            "fixture or the read-only client. Refusing to read a real shop from the harness."
        )
    task = cache.warm(days)
    if task is not None:
        await task
