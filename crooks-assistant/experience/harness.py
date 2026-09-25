"""Driving the assistant the way the tablet drives it, and writing down what came back.

The one rule this file exists to keep: a scenario must go through the same code a person's
voice goes through. `POST /turn` with a `text` body is not a shortcut around the application —
it is the exact point the audio path arrives at once Scribe or whisper has finished, and
everything after it (the affirmation check, the revocation of pending cards, the epoch, the
branch, the lane router, the recipe, the presenters, the timeline) is shared. So a scenario
injects a transcript there, and nothing here reaches past the HTTP boundary to help it along.

What is swapped is what the Mac talks to: Shopify and Gmail become the golden world, and the
model provider becomes one that records what it was asked and answers in a fixed sentence. Those
are the same three seams the runtime itself uses. Nothing else is faked, and in particular no
part of the presentation, routing or action layer is — those are what is being measured.

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
    """A model that never thinks and always remembers being asked.

    A scenario asserting "this was answered without the model" needs the model to be countable,
    not absent: a provider that raises would make a deferral look like a crash, and one that is
    missing would let a recipe quietly stop deferring without any test noticing.
    """

    def __init__(self, reply: str = "[model answer]") -> None:
        self.reply = reply
        self.calls: list[str] = []

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
        return TurnResult(text=self.reply, session_id=session_id)


@dataclass
class Capture:
    """One interaction, and everything that can be said about it without opinion."""

    scenario: str = ""
    kind: str = "voice"                 # voice | touch | touch_then_voice
    command: str = ""
    session_id: str = ""
    branch_id: str = ""
    status: int = 0

    lane: str = ""
    recipe_id: str = ""
    intent_family: str = ""
    confidence: float | None = None
    model_calls: int = 0
    tools: list[str] = field(default_factory=list)

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
            "intent_family": self.intent_family, "confidence": self.confidence,
            "model_calls": self.model_calls, "tools": list(self.tools), "reads": list(self.reads),
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
                 store: Any, gmail: Any, *, live: bool = False) -> None:
        self.client = client
        self.runtime = runtime
        self.provider = provider
        self.store = store
        self.gmail = gmail
        self.live = live
        self.captures: list[Capture] = []

    # ---------------------------------------------------------------- configuration

    def configure(self, *, writes: bool = True, logins: str = OWNER_LOGIN) -> None:
        """Put the backend in the state the tablet meets in production.

        Changes ON and an allow-list naming the caller, because a scenario about which actions
        a card offers proves nothing against a backend where every action is switched off. What
        this does NOT do is make a write possible: the fixture clients refuse every mutation,
        and in live mode the read-only guard refuses it before that.
        """
        from app.main import app

        self.runtime.settings = self.runtime.settings.model_copy(
            update={"writes_enabled": writes, "allowed_logins": logins,
                    "writes_local_owner": False, "tailscale_verify": False}
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
            lane=str(payload.get("lane") or ""), recipe_id=str(payload.get("recipe_id") or ""),
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
        branch = self.branch(session_id, capture.branch_id)
        entity = getattr(branch, "entity", None)
        if isinstance(entity, dict) and entity.get("ref"):
            capture.entity = {"kind": str(entity.get("kind") or ""), "ref": str(entity["ref"]),
                              "label": str(entity.get("label") or "")}
        workflow = getattr(branch, "workflow", None)
        capture.set_id = str(getattr(workflow, "set_id", "") or "") if workflow is not None else ""
        intent = payload.get("intent")
        if isinstance(intent, dict):
            capture.intent_family = str(intent.get("family") or "")
            confidence = intent.get("confidence")
            capture.confidence = float(confidence) if isinstance(confidence, (int, float)) else None
        return capture


@asynccontextmanager
async def harness(*, live: bool = False, writes: bool = True):
    """A running assistant against the golden world, torn down afterwards.

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
    ScribeClient.health = fake_scribe_health
    VoiceClient.health = lambda _self: (True, "harness")
    try:
        async with app.router.lifespan_context(app):
            runtime = app.state.runtime
            provider = RecordingProvider()
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
                harness_ = Harness(client, runtime, provider, store, gmail, live=live)
                harness_.configure(writes=writes)
                yield harness_
    finally:
        ScribeClient.health = scribe_health
        VoiceClient.health = voice_health


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
