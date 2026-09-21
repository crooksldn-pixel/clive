"""The test session: everything the Mac and the tablet do, written to one timeline, and read
back as a report. Held here: the session state on disk; the writer off the turn's path and
never a credential; the routes (the Mac starts and stops, the tablet only reports); and one
mocked hour — ten kinds of interaction through the real routes with fakes behind them —
from which the report is written and every interaction is reconstructed field by field."""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.actions.ledger import NullLedger
from app.clients.shopify import ShopifyError
from app.main import app
from app.observability import timeline as timeline_module
from app.observability.report import CLASSES, build_report, reconstruct, write_report
from app.observability.session import AlreadyActive, TestSessions
from app.observability.timeline import NullTimeline, Timeline, read_events, scrub
from app.providers.base import TurnResult
from app.session.manager import SessionManager
from app.tools import registry, shopify_tools
from app.tools.dispatch import dispatch
from tests.conftest import FakeShopify
from tests.test_actions_routes import PROXIED, FakeProvider, configure
from tests.test_context import CUSTOMER_NODE, ORDER_NODE, inbox

ORDER = ORDER_NODE["id"]
STRANGER = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}


# --------------------------------------------------------------------------- the state on disk


class Clock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_a_session_is_started_stopped_and_found_again_from_the_files(tmp_path):
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    assert store.active() is None and store.last() is None and store.find() is None
    session = store.start("First hour!")
    assert session.test_session_id.startswith("ts-") and session.test_session_id.endswith("-first-hour") and session.active
    assert (store.root / "active.json").exists() and oct(store.root.stat().st_mode & 0o777) == "0o700"
    assert oct((store.root / "active.json").stat().st_mode & 0o777) == "0o600"
    with pytest.raises(AlreadyActive):
        store.start("second")
    # Another process (the CLI) reads the same truth from the file, within the recheck window.
    other = TestSessions(tmp_path, clock=clock)
    assert other.active() is not None and other.active().test_session_id == session.test_session_id
    clock.now += 2
    stopped = store.stop()
    assert stopped is not None and stopped.stopped_at == clock.now and not stopped.active
    assert store.active() is None and store.last().test_session_id == session.test_session_id
    assert store.stop() is None
    store.timeline_path(session).write_text("{}\n")
    assert store.find() == store.timeline_path(session), "no name: the last session's timeline"
    assert store.find(session.test_session_id) == store.timeline_path(session)
    assert store.find("ts-") == store.timeline_path(session), "a prefix is enough"
    assert store.find("../etc/passwd") is None and store.find("nothing-like-it") is None


def test_the_writer_writes_nothing_without_a_session_and_scrubs_what_it_writes(tmp_path):
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    timeline = Timeline(store, clock=clock)
    assert timeline.emit("turn_started", session_id="s1") is None and timeline.active is None
    session = timeline.start("scrub")
    event = timeline.emit(
        "tool_finished", source="mac", session_id="s1", tool="x", ok=True,
        headers={"Authorization": "Bearer abcdefghijklmnopqrstuvwxyz"}, nonce="secret-nonce", args={"token": "shpat_0123456789abcdef", "note": "hi"},
        answer="the key is shpat_0123456789abcdefABCDEF and the token ya29.a0AfH6SMBxyz-1234567890 and Bearer ZZZZZZZZZZZZZZZZZZZZZZ.",
        nothing=None,
    )
    assert event["seq"] == 2 and event["test_session_id"] == session.test_session_id and event["kind"] == "tool_finished"
    assert event["headers"] == "[withheld]" and event["nonce"] == "[withheld]" and event["args"] == {"token": "[withheld]", "note": "hi"}
    assert "shpat_" not in event["answer"] and "ya29" not in event["answer"] and "ZZZZ" not in event["answer"] and event["answer"].count("[secret]") == 3
    assert "nothing" not in event, "a None field is not written"
    assert timeline.flush()
    path = store.timeline_path(session)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    lines = read_events(path)
    assert [e["kind"] for e in lines] == ["session_started", "tool_finished"]
    assert timeline.stop() is not None and read_events(path)[-1]["kind"] == "session_stopped"
    assert timeline.emit("turn_started") is None, "stopped: nothing more is written"
    assert timeline.counts["dropped"] == 0 and timeline.counts["written"] == 3


def test_scrub_bounds_depth_length_and_kinds():
    deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": 1}}}}}}}}
    out = scrub(deep)
    assert out["a"]["b"]["c"]["d"]["e"]["f"]["g"] == "[deep]"
    assert scrub("x" * 7000).endswith("…") and len(scrub("x" * 7000)) == 6001
    assert scrub(b"bytes") == "<5 bytes>" and scrub(float("nan")) is None and scrub(True) is True
    assert scrub({"X-API-Key": "k", "Cookie": "c", "fine": [1, "two", {"password": "p"}]}) == {"X-API-Key": "[withheld]", "Cookie": "[withheld]", "fine": [1, "two", {"password": "[withheld]"}]}


def test_the_null_timeline_is_silent_and_the_process_default():
    null = NullTimeline()
    assert null.active is None and null.emit("x", a=1) is None and null.flush()
    assert isinstance(timeline_module.current(), Timeline)


# ---------------------------------------------------------------------------- the routes


@pytest.fixture()
async def client(monkeypatch, tmp_path):
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.observability.timeline import install
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = FakeProvider()
        runtime.actions.ledger = NullLedger()
        runtime.sessions = SessionManager()
        # A timeline of this test's own, in its own directory; the process-wide one follows it.
        runtime.tests = TestSessions(tmp_path / "logs")
        runtime.timeline = install(Timeline(runtime.tests))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.runtime = runtime
            c.tmp = tmp_path
            yield c
        runtime.timeline.stop()


async def test_the_session_is_controlled_from_the_mac_only_and_seen_by_every_poll(client):
    assert (await client.post("/test-session/start", json={"name": "x"}, headers=PROXIED)).status_code == 403
    assert (await client.get("/test-session/status", headers=PROXIED)).status_code == 403
    assert (await client.post("/test-session/stop", headers=PROXIED)).status_code == 403
    status = (await client.get("/test-session/status")).json()
    assert status == {"active": False, "last": None}
    health = (await client.get("/health")).json()
    assert health["observability"] == {"test_session": None, "name": None}
    started = (await client.post("/test-session/start", json={"name": "Route check"})).json()
    assert started["started"] and started["test_session_id"].endswith("-route-check") and started["path"].endswith(".jsonl")
    again = await client.post("/test-session/start", json={"name": "another"})
    assert again.status_code == 409 and again.json()["code"] == "already_active"
    health = (await client.get("/health")).json()
    assert health["observability"] == {"test_session": started["test_session_id"], "name": "Route check"}, "the cached health answer still says what is on now"
    status = (await client.get("/test-session/status")).json()
    assert status["active"] and status["test_session_id"] == started["test_session_id"] and "events" in status
    stopped = (await client.post("/test-session/stop")).json()
    assert stopped["stopped"] and stopped["test_session_id"] == started["test_session_id"]
    assert (await client.post("/test-session/stop")).json() == {"stopped": False, "detail": "No test session is running."}
    assert (await client.get("/health")).json()["observability"]["test_session"] is None
    status = (await client.get("/test-session/status")).json()
    assert not status["active"] and status["last"]["test_session_id"] == started["test_session_id"]


async def test_the_tablet_reports_are_bounded_owned_and_never_waited_for(client):
    from tests.test_actions_routes import OWNER

    configure(client, logins=f"{OWNER}, other@example.com")
    assert (await client.post("/telemetry", json={"events": [{"kind": "render"}]}, headers=PROXIED)).status_code == 204, "no session: dropped, still 204"
    await client.post("/test-session/start", json={"name": "telemetry"})
    # A conversation belongs to its first login; a stranger's report about it is dropped.
    assert (await client.post("/turn", json={"text": "hello", "session_id": "mine"}, headers=PROXIED)).status_code == 200
    response = await client.post("/telemetry", json={"session_id": "mine", "events": [{"kind": "render", "screen": "orb"}]}, headers=STRANGER)
    assert response.status_code == 204 and response.headers.get("x-crooks-telemetry") is None
    response = await client.post("/telemetry", json={"session_id": "mine", "events": [
        {"kind": "render", "screen": "orb", "turn_id": "turn_x", "authorization": "leak", "cookie": "leak", "viewport": {"w": 800, "h": 1280}},
        {"kind": "Not A Kind"}, "junk", {"kind": "exception", "message": "x" * 5000},
    ]}, headers=PROXIED)
    assert response.status_code == 204 and response.headers["x-crooks-telemetry"] == "2"
    big = {"session_id": "mine", "events": [{"kind": "scroll", "depth": i} for i in range(300)]}
    response = await client.post("/telemetry", json=big, headers=PROXIED)
    assert response.status_code == 204 and response.headers["x-crooks-telemetry"] == "200", "two hundred at most per batch"
    assert (await client.post("/telemetry", content=b"x" * 70_000, headers={**PROXIED, "content-type": "application/json"})).status_code == 204
    assert (await client.post("/telemetry", content=b"{not json", headers={**PROXIED, "content-type": "application/json"})).status_code == 204
    stopped = (await client.post("/test-session/stop")).json()
    client.runtime.timeline.flush()
    events = read_events(Path(stopped["path"]))
    tablet = [e for e in events if e["source"] == "tablet"]
    assert len(tablet) == 202
    first = tablet[0]
    assert first["kind"] == "tablet_render" and first["turn_id"] == "turn_x" and first["session_id"] == "mine" and first["viewport"] == {"w": 800, "h": 1280}
    assert "authorization" not in first and "cookie" not in first
    assert len(tablet[1]["message"]) == 2000


# ------------------------------------------------------------------------- the mocked hour


class Store(FakeShopify):
    """The order and its customer, by query name; the note as the tools read and write it."""

    def __init__(self) -> None:
        super().__init__([])
        self.order = copy.deepcopy(ORDER_NODE)
        self.customer = copy.deepcopy(CUSTOMER_NODE)
        self.mutations: list[tuple[str, dict]] = []
        self.scopes = {"read_orders", "write_orders", "write_merchant_managed_fulfillment_orders", "write_inventory"}

    async def graphql(self, query, variables=None):
        self.queries.append((query, variables or {}))
        v = variables or {}
        if "CrooksScopes" in query:
            return {"data": {"currentAppInstallation": {"accessScopes": [{"handle": h} for h in sorted(self.scopes)]}}}
        if "CrooksOrderByName" in query:
            digits = str(v.get("q", "")).split(":")[-1]
            return {"data": {"orders": {"edges": [{"node": self.order}] if self.order["name"].endswith(digits) else []}}}
        if "CrooksOrderContext" in query or "CrooksOrderNote" in query or "CrooksOrderTags" in query:
            return {"data": {"order": self.order if v.get("id") == self.order["id"] else None}}
        if "CrooksCustomerOrders" in query:
            return {"data": {"customer": self.customer if v.get("id") == self.customer["id"] else None}}
        raise AssertionError(f"unexpected query: {query[:60]}")

    async def mutate(self, name: str, variables: dict) -> dict:
        self.mutations.append((name, dict(variables)))
        if name == "order_note_set":
            self.order["note"] = variables["note"]
            return {"data": {"orderUpdate": {"order": {"id": variables["id"], "name": self.order["name"], "note": self.order["note"]}, "userErrors": []}}}
        raise AssertionError(f"unexpected mutation {name}")


class ScriptedProvider(FakeProvider):
    """Claude, scripted: what it calls and what it says follow from the words it is asked."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    async def turn(self, session_id: str, text: str) -> TurnResult:
        session = self.runtime.sessions.get_or_create(session_id)
        session.turns += 1
        calls: list = []
        # The owner's own line: after the clock line, before the Mac's prefetch note.
        lines = text.split("\n")
        words = (lines[1] if len(lines) > 1 and lines[0].startswith("[Now:") else lines[0]).lower()
        steps = [("model", 80.0)]

        async def call(name, args):
            out = await dispatch(name, args, session=session, timeout_s=5, calls=calls)
            steps.append((f"tool:{name}", 80.0 + 40 * len(steps)))
            return out

        if "order 1938" in words and "note" not in words and "cancel" not in words:
            await asyncio.sleep(0.05)   # the Mac's own read of the order lands beside the model
            answer = "Order 1938: paid, not shipped yet. One pair of Yard Jeans, sixty pounds, for Daniel Sear."
        elif "jeans" in words and "stock" not in words:
            await call("shopify_product_info", {"product": "Yard Jeans", "size": "medium"})
            answer = "The Yard Jeans in a medium have a thirty-two inch inseam."
        elif "store credit" in words:
            await call("shopify_customer_store_credit_add", {"customer_id": CUSTOMER_NODE["id"], "amount": "10.00"})
            answer = "I can't add store credit; that isn't something I can do from here."
        elif "daniel" in words:
            await call("shopify_find_customer", {"query": "Daniel Sear"})
            await call("shopify_customer_history", {"customer_id": CUSTOMER_NODE["id"]})
            answer = "Daniel Sear has three orders with you, four hundred and ten pounds in all."
        elif "email" in words:
            await call("gmail_search", {"query": "1938", "days": 7})
            answer = "One email from Daniel about order 1938, asking to send it to his work address."
        elif "note" in words:
            await call("shopify_order_note_append", {"order_id": ORDER, "note": "Customer asked for an exchange"})
            answer = "The note is ready on the tablet; tapping the card applies it."
        elif "stock" in words:
            await call("shopify_inventory", {"product": "Yard Jeans"})
            answer = "That stock check failed: Shopify is rate-limiting us. Try again in a moment."
        elif "sales" in words:
            answer = "Twelve orders today, four hundred and thirty pounds."
        else:
            answer = "I did not follow that."
        return TurnResult(text=answer, tool_calls=calls, session_id=session_id, steps=steps)


def canned(name: str, result: dict | None = None, *, error: Exception | None = None):
    """A registered tool answered from a table (or raising), for the mocked hour."""
    spec = registry.get(name)

    async def handler(**kwargs):
        if error is not None:
            raise error
        return dict(result or {})

    return replace(spec, handler=handler)


PRODUCT = {"query": "Yard Jeans", "products": [{"product_id": "gid://shopify/Product/31", "title": "Yard Jeans", "subtitle": "Blue Wash", "description": "Straight cut.", "measurements": [{"size": "M", "inseam": "32"}], "image_url": "/media/shopify/0123456789abcdef0123456789abcdef/200?u=abc"}]}
CUSTOMER_MATCH = {"query": "Daniel Sear", "customers": [{"customer_id": CUSTOMER_NODE["id"], "name": "Daniel Sear", "email": "daniel@example.com", "orders": 3, "spent": "410.00 GBP"}]}
EMAILS = {"query": "1938", "count": 1, "threads": [{"thread_id": "18f2a9c0b1d2e3f4", "from": "Daniel Sear", "from_email": "daniel@example.com", "subject": "Address for 1938", "date": "Mon, 8 Sep 2026 10:12:00 +0100", "snippet": "Please send it to my work instead", "likely_bulk": False, "authenticated": True}]}


async def tablet(client, session_id: str, turn_id: str, *events: dict) -> None:
    """What the tablet reports about a turn, as its telemetry module would batch it."""
    batch = [{"turn_id": turn_id, **e} for e in events]
    response = await client.post("/telemetry", json={"session_id": session_id, "events": batch}, headers=PROXIED)
    assert response.status_code == 204 and response.headers["x-crooks-telemetry"] == str(len(batch))


def card(kind: str, ref: str = "", **extra) -> dict:
    return {"type": kind, **({"ref": ref} if ref else {}), **extra}


def render(t: int, screen: str, *cards: dict, **extra) -> dict:
    return {"kind": "render", "t": t, "screen": screen, "cards": list(cards), "viewport": {"w": 800, "h": 1280, "dpr": 1}, "document": {"height": 1280, "cards_height": extra.pop("cards_height", 900), "cards_visible": 1000}, "overflow": {"long_scroll": extra.pop("long_scroll", False), "clipped": 0}, **extra}


async def mocked_hour(client, monkeypatch) -> tuple[Path, dict]:
    """Ten interactions, through the real routes, with fakes behind them. Returns the timeline's
    path and the turns' ids by scenario."""
    configure(client)
    runtime = client.runtime
    store = Store()
    runtime.shopify = store
    shopify_tools.bind(store, threads_for=inbox())
    runtime.provider = ScriptedProvider(runtime)
    monkeypatch.setitem(registry._REGISTRY, "shopify_product_info", canned("shopify_product_info", PRODUCT))
    monkeypatch.setitem(registry._REGISTRY, "shopify_find_customer", canned("shopify_find_customer", CUSTOMER_MATCH))
    monkeypatch.setitem(registry._REGISTRY, "gmail_search", canned("gmail_search", EMAILS))
    monkeypatch.setitem(registry._REGISTRY, "shopify_inventory", canned("shopify_inventory", error=ShopifyError("Shopify is rate-limiting us; try again in a moment.")))
    started = (await client.post("/test-session/start", json={"name": "Mocked hour"})).json()
    assert started["started"]
    session_id = "tab1"
    ids: dict[str, str] = {}
    t = 1_800_000_000_000

    async def turn(text: str) -> dict:
        response = await client.post("/turn", json={"text": text, "session_id": session_id, "speak": True}, headers=PROXIED)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["test_session_id"] == started["test_session_id"] and data["turn_id"].startswith("turn_")
        await client.post("/telemetry", json={"session_id": session_id, "events": [{"kind": "turn_response", "turn_id": data["turn_id"], "ms": 900, "items": [i["type"] for i in data["ui"]], "answer_chars": len(data["answer"])}]}, headers=PROXIED)
        return data

    # 1. a successful order lookup: the Mac's own procedure, no model on the critical path
    data = await turn("show me order 1938")
    assert data["lane"] == "FAST" and data["recipe_id"] == "order_lookup", data["lane"]
    ids["order"] = data["turn_id"]
    assert "order" in [i["type"] for i in data["ui"]], data["ui"]
    await tablet(client, session_id, ids["order"],
                 render(t, "context", card("order", ORDER, sections=["Items · 1", "Shipping", "Customer", "Email"], actions=[{"id": "note", "enabled": True}, {"id": "fulfil", "enabled": True}, {"id": "cancel", "enabled": True}], images={"count": 1, "missing": 0, "loaded": 1}), long_scroll=True, cards_height=1900),
                 {"kind": "navigate", "t": t, "nav": "new", "index": 0, "entities": [ORDER]},
                 {"kind": "scroll", "t": t + 4000, "depth": 640, "height": 1900, "width": 1000},
                 {"kind": "speak", "t": t + 1200, "via": "player", "ms": 700})
    await client.post("/speak", json={"text": data["answer"], "session_id": session_id, "turn_id": ids["order"]}, headers=PROXIED)
    # 2. product navigation
    t += 30_000
    data = await turn("what's the inseam on the yard jeans in a medium")
    ids["product"] = data["turn_id"]
    await tablet(client, session_id, ids["product"],
                 render(t, "context", card("product", "gid://shopify/Product/31", images={"count": 1, "missing": 1, "loaded": 0})),
                 {"kind": "image_failed", "t": t + 300, "src": "/media/shopify/0123456789abcdef0123456789abcdef/200"},
                 {"kind": "navigate", "t": t + 9000, "nav": "stack_chip", "entity": ORDER, "to": 0})
    # 3. customer navigation
    t += 30_000
    data = await turn("has daniel bought from us before")
    ids["customer"] = data["turn_id"]
    await tablet(client, session_id, ids["customer"],
                 render(t, "context", card("customer", CUSTOMER_NODE["id"], sections=["Orders", "Email"])),
                 {"kind": "tab", "t": t + 2000, "label": "Email", "name": "customer", "entity": CUSTOMER_NODE["id"]},
                 {"kind": "navigate", "t": t + 1500, "nav": "back", "from": 2, "to": 1})
    # 4. email lookup
    t += 30_000
    data = await turn("any email from him about 1938")
    ids["email"] = data["turn_id"]
    await tablet(client, session_id, ids["email"], render(t, "context", card("email_list")))
    # 5. a successful action proposal, and 6. the same withdrawn by the next instruction
    t += 30_000
    data = await turn("add a note to order 1938 that the customer asked for an exchange")
    ids["proposal"] = data["turn_id"]
    assert any(c.get("proposal_id") for c in data["tool_calls"]), data["tool_calls"]
    withdrawn = next(c["proposal_id"] for c in data["tool_calls"] if c.get("proposal_id"))
    await tablet(client, session_id, ids["proposal"],
                 render(t, "context", card("confirmation", ORDER, proposal_id=withdrawn, surface={"kind": "tap_commit", "state": "arming"})),
                 {"kind": "gesture", "t": t + 400, "gesture": "down", "name": "tap_commit", "state": "arming", "proposal_id": withdrawn})
    t += 10_000
    data = await turn("what were sales today")
    ids["withdrawn_by"] = data["turn_id"]
    assert data["revoked"] == [withdrawn]
    await tablet(client, session_id, ids["withdrawn_by"], render(t, "orb"))
    # 7. a proposal committed and verified
    t += 30_000
    data = await turn("add a note to order 1938 that the customer asked for an exchange")
    ids["committed"] = data["turn_id"]
    committed = next(c["proposal_id"] for c in data["tool_calls"] if c.get("proposal_id"))
    await tablet(client, session_id, ids["committed"],
                 render(t, "context", card("confirmation", ORDER, proposal_id=committed, surface={"kind": "tap_commit", "state": "armed"})),
                 {"kind": "gesture", "t": t + 900, "gesture": "down", "name": "tap_commit", "state": "armed", "proposal_id": committed},
                 {"kind": "gesture", "t": t + 1000, "gesture": "up", "name": "tap_commit", "state": "committing", "proposal_id": committed})
    response = await client.post(f"/actions/{committed}/commit", data={"session_id": session_id}, headers=PROXIED)
    assert response.status_code == 200 and response.json()["status"] == "verified", response.text
    await tablet(client, session_id, ids["committed"], {"kind": "action_commit", "t": t + 1600, "proposal_id": committed, "status": "verified", "code": "verified", "outcome": "answered", "ms": 580})
    await client.post("/speak", json={"text": response.json()["spoken"], "session_id": session_id, "turn_id": ids["committed"]}, headers=PROXIED)
    # 8. an unsupported request: store credit
    t += 30_000
    data = await turn("give daniel ten pounds of store credit")
    ids["unsupported"] = data["turn_id"]
    await tablet(client, session_id, ids["unsupported"], render(t, "orb"))
    # 9. a tool failure
    t += 30_000
    data = await turn("how much stock of the yard jeans")
    ids["tool_failure"] = data["turn_id"]
    await tablet(client, session_id, ids["tool_failure"], render(t, "context", card("error")))
    # 10. a frontend render error
    t += 30_000
    data = await turn("show me order 1938")
    ids["render_error"] = data["turn_id"]
    await tablet(client, session_id, ids["render_error"],
                 {"kind": "exception", "t": t + 50, "message": "TypeError: Cannot read properties of undefined (reading 'lines')", "file": "/static/ui.js", "line": 412, "col": 9},
                 render(t + 60, "context", card("order", ORDER), skipped=["order"], errors=["Something went wrong"]),
                 {"kind": "connectivity", "t": t + 5000, "state": "offline"}, {"kind": "connectivity", "t": t + 9000, "state": "online"})
    stopped = (await client.post("/test-session/stop")).json()
    assert stopped["stopped"]
    runtime.timeline.flush()
    return Path(stopped["path"]), ids


async def test_the_mocked_hour_is_reconstructed_interaction_by_interaction_and_reported(client, monkeypatch):
    path, ids = await mocked_hour(client, monkeypatch)
    events = read_events(path)
    assert events[0]["kind"] == "session_started" and events[-1]["kind"] == "session_stopped"
    for event in events:
        assert {"ts", "iso", "seq", "test_session_id", "source", "kind"} <= event.keys()
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    rec = reconstruct(events)
    assert [t.turn_id for t in rec.turns] == list(ids.values()), "every turn, in order, and no other"
    by = {name: rec.turn(turn_id) for name, turn_id in ids.items()}

    # 1. the order lookup: the fast lane's own procedure — the reads, the card, the voice,
    # the scroll, and NO model call at all. The timeline says which lane and which recipe.
    order = by["order"]
    assert order.input == "text" and order.question == "show me order 1938" and order.outcome == "successful" and order.classes == []
    assert order.lane["lane"] == "FAST" and order.lane["family"] == "order_lookup"
    assert order.fast["recipe_id"] == "order_lookup" and order.fast["hit"] is True and order.fast["ms"] > 0
    assert order.model is None and order.latency("claude") is None, "the fast lane does not call the model"
    assert order.performance["fast_path_hit"] is True and order.performance["model_calls"] == 0
    assert order.read_plans and order.read_plans[0]["label"] == "order_lookup"
    assert [x.tool for x in order.tools] == ["shopify_find_order", "shopify_order_detail"]
    assert order.tools[0].outcome == "ok" and order.tools[0].result["orders"] == {"count": 1, "ids": [ORDER, CUSTOMER_NODE["id"]]}
    assert order.tools[0].tool_call_id.startswith("tc_") and order.tools[0].ms is not None
    assert "order" in order.ui and {"type": "order", "ref": ORDER} in order.ui_entities
    assert order.latency("total") > 0 and order.latency("shopify") is not None and order.latency("round_trip") == 900
    assert order.latency("tts_first_byte") == 700, "the tablet's own measure, when ElevenLabs is not there"
    # The TTS record counts what was SPOKEN; the timeline's copy of the answer is redacted,
    # so the two are no longer the same length — and that difference is the point.
    assert order.tts and order.tts[0]["ok"] is False and order.tts[0]["failure"] == "no_key" and order.tts[0]["chars"] >= len(order.answer)
    assert CUSTOMER_NODE["displayName"] not in order.answer, "a customer's name is not written down"
    assert "[name]" in order.answer and "CROOKS-1938" in order.answer, "redacted by name, not by wholesale removal"
    render_ = order.render
    assert render_["screen"] == "context" and render_["cards"][0]["type"] == "order" and render_["cards"][0]["actions"][0] == {"id": "note", "enabled": True}
    assert render_["overflow"]["long_scroll"] is True and order.tablet_events("scroll")[0]["depth"] == 640
    assert order.finished["speak_requested"] is True and order.finished["tts_prefetched"] is True
    assert order.cluster == "orders"
    # 2. product navigation: the card, its failed image, the chip back to the order
    product = by["product"]
    assert [x.tool for x in product.tools] == ["shopify_product_info"] and product.tools[0].args == {"product": "Yard Jeans", "size": "medium"}
    assert product.render["cards"][0]["type"] == "product" and product.tablet_events("image_failed")[0]["src"].startswith("/media/shopify/")
    assert "UI_RENDER_ERROR" in product.classes and product.outcome == "partial" and product.cluster == "products"
    assert product.tablet_events("navigate")[0]["nav"] == "stack_chip"
    # 3. customer navigation: two tools, a tab, the screen left at once
    customer = by["customer"]
    assert [x.tool for x in customer.tools] == ["shopify_find_customer", "shopify_customer_history"] and all(x.outcome == "ok" for x in customer.tools)
    assert customer.hydrations and customer.hydrations[-1]["hydration"] == "customer"
    assert customer.tablet_events("tab")[0]["label"] == "Email" and "UI_NAVIGATION_PROBLEM" in customer.classes and customer.cluster == "customers"
    # 4. email lookup
    email = by["email"]
    assert [x.tool for x in email.tools] == ["gmail_search"] and email.tools[0].result["threads"] == {"count": 1, "ids": ["18f2a9c0b1d2e3f4"]}
    assert email.outcome == "successful" and email.cluster == "email" and email.render["cards"][0]["type"] == "email_list"
    # 5 and 6. the proposal, staged and delivered, then withdrawn by the next instruction
    proposal = by["proposal"]
    assert len(proposal.proposals) == 1
    withdrawn = proposal.proposals[0]
    assert withdrawn.operation == "order_note_append" and withdrawn.risk == "AMBER" and withdrawn.interaction == "tap_commit" and withdrawn.reversible is True
    assert withdrawn.staged_at and withdrawn.delivered and not withdrawn.committed and withdrawn.status == "REVOKED" and withdrawn.reason == "new instruction"
    assert [e["event"] for e in withdrawn.events] == ["PROPOSED", "DELIVERED", "REVOKED"]
    staged = next(x for x in proposal.tools if x.outcome == "staged")
    assert staged.tool == "shopify_order_note_append" and staged.proposal_id == withdrawn.proposal_id and [x.tool for x in proposal.tools][0] == "shopify_find_order", "the Mac's own lookup ran first"
    assert withdrawn.tablet and withdrawn.tablet[0]["kind"] == "tablet_render"
    assert by["withdrawn_by"].finished["revoked"] == [withdrawn.proposal_id] and proposal.cluster == "actions"
    # 7. the proposal committed and proven
    committed_turn = by["committed"]
    committed = committed_turn.proposals[0]
    assert committed.committed and committed.status == "VERIFIED" and committed.verified is True and committed.code == "verified"
    assert [e["event"] for e in committed.events][:5] == ["PROPOSED", "DELIVERED", "EXECUTING", "EXECUTED", "VERIFIED"]
    assert committed.commits and committed.commits[0]["code"] == "verified" and committed.latency_ms is not None
    assert any(e["kind"] == "tablet_action_commit" and e["status"] == "verified" for e in committed.tablet)
    assert [g["gesture"] for g in committed_turn.tablet_events("gesture")] == ["down", "up"]
    undo = next(p for p in rec.proposals.values() if p.undo_of == committed.proposal_id)
    assert undo.turn_id == committed_turn.turn_id and undo.status == "PENDING"
    assert committed_turn.outcome == "successful"
    # 8. the unsupported request
    unsupported = by["unsupported"]
    assert unsupported.tools[0].tool == "shopify_customer_store_credit_add" and unsupported.tools[0].outcome == "refused" and unsupported.tools[0].missing_capability == "shopify_customer_store_credit_add"
    assert unsupported.classes == ["MISSING_CAPABILITY"] and unsupported.outcome == "failed"
    # 9. the tool failure
    failure = by["tool_failure"]
    assert failure.tools[0].outcome == "error" and "rate-limiting" in failure.tools[0].error and failure.classes == ["TOOL_ERROR"] and failure.outcome == "failed"
    # 10. the frontend render error, and the connection lost and back
    broken = by["render_error"]
    assert "UI_RENDER_ERROR" in broken.classes and broken.tablet_events("exception")[0]["line"] == 412 and broken.render["skipped"] == ["order"]
    assert [e["state"] for e in broken.tablet_events("connectivity")] == ["offline", "online"]
    assert not rec.orphans, "every event belongs to a turn"

    # The report, from the file alone, useful without it.
    out_dir = client.tmp / "reports"
    written = write_report(path, out_dir)
    assert written == out_dir / f"{rec.session['test_session_id']}.md" and oct(written.stat().st_mode & 0o777) == "0o600"
    text = written.read_text(encoding="utf-8")
    for n, heading in enumerate(("Session summary", "Performance", "Requests", "Tool usage", "Failures", "Unsupported requests", "UI usage", "Action engine", "Context quality", "Response quality", "Anticipation", "Top improvement opportunities"), 1):
        assert f"## {n}. {heading}" in text, heading
    assert "Interactions: **10** turns" in text and "Successful **" in text
    assert "shopify_customer_store_credit_add" in text and "requested 1 time(s)" in text
    assert "Class" in text and "TOOL_ERROR" in text and "MISSING_CAPABILITY" in text and "UI_RENDER_ERROR" in text
    assert committed.proposal_id in text and withdrawn.proposal_id in text and "new instruction" in text
    assert "Failed image loads" in text and "Long scroll surfaces" in text and "Frontend exceptions" in text
    assert "Exposed but never used" in text and "fulfil" in text
    assert "Requested capability not built: shopify_customer_store_credit_add" in text
    assert "shpat_" not in text and "Bearer" not in text
    for cls in CLASSES:
        assert cls in text, "every class is explained"


async def test_a_report_can_be_written_from_a_timeline_with_nothing_in_it(tmp_path):
    empty = tmp_path / "ts-20260909-000000-empty.jsonl"
    empty.write_text("")
    rec, markdown = build_report(empty, tools_registered=["shopify_find_order"])
    assert rec.turns == [] and rec.session["test_session_id"] == "ts-20260909-000000-empty"
    assert "## 1. Session summary" in markdown and "## 12. Top improvement opportunities" in markdown and "Interactions: **0** turns" in markdown
    assert "_Nothing in this session's evidence calls for a change._" in markdown


def test_the_cli_marks_a_session_on_disk_when_the_backend_is_not_running(tmp_path, monkeypatch, capsys):
    import scripts.test_session as cli

    class Settings:
        port = 1   # nothing listens here
        log_dir = tmp_path

    monkeypatch.setattr(cli, "_settings", lambda: Settings())
    monkeypatch.setattr(cli, "_call", lambda *a, **k: None)
    assert cli.main(["start", "--name", "Offline start"]) == 0
    session_id = capsys.readouterr().out.strip()
    assert session_id.endswith("-offline-start")
    assert cli.main(["start", "--name", "again"]) == 1
    assert cli.main(["status"]) == 0 and session_id in capsys.readouterr().out
    assert cli.main(["stop"]) == 0 and capsys.readouterr().out.strip() == session_id
    assert cli.main(["stop"]) == 1
    assert cli.main(["report"]) == 1, "no timeline was written: nothing to report"
    (tmp_path / "test-sessions" / f"{session_id}.jsonl").write_text(json.dumps({"ts": 1.0, "seq": 1, "kind": "session_started", "test_session_id": session_id, "source": "mac", "name": "Offline start"}) + "\n")
    assert cli.main(["report", "--out", str(tmp_path / "reports")]) == 0
    written = Path(capsys.readouterr().out.strip())
    assert written == tmp_path / "reports" / f"{session_id}.md" and "## 1. Session summary" in written.read_text()


async def test_the_live_marks_survive_the_allow_list_and_carry_no_words(client):
    """V0.5 invariant 11. The tablet's state machine measures what one interaction felt like
    (web/live-state.js) and posts it as `live_marks`. The ingest allow-list is the reason
    nothing else can ride along — which is exactly why the measurements themselves have to be
    ON it, or the evidence the gate asks for would be stripped in silence."""
    from tests.test_actions_routes import OWNER

    configure(client, logins=OWNER)
    await client.post("/test-session/start", json={"name": "live marks"})
    assert (await client.post("/turn", json={"text": "hello", "session_id": "mine"}, headers=PROXIED)).status_code == 200
    response = await client.post("/telemetry", json={"session_id": "mine", "events": [{
        "kind": "live_marks", "turn_id": "turn_x", "state": "IDLE",
        "ack_ms": 0, "transcript_ms": 812, "progress_ms": 940, "useful_ms": 1560, "responding_ms": 2100,
        "partials": 3, "heard_chars": 47, "interruptions": 1, "faults": 0,
        # What the machine was never given, offered anyway: the route drops it.
        "heard": "check today's orders", "answer": "14 today",
    }]}, headers=PROXIED)
    assert response.status_code == 204 and response.headers["x-crooks-telemetry"] == "1"

    stopped = (await client.post("/test-session/stop")).json()
    client.runtime.timeline.flush()
    marks = [e for e in read_events(Path(stopped["path"])) if e.get("kind") == "tablet_live_marks"]
    assert len(marks) == 1
    event = marks[0]
    # Every measurement the evidence gate names, landed and intact.
    assert event["ack_ms"] == 0 and event["transcript_ms"] == 812
    assert event["progress_ms"] == 940 and event["useful_ms"] == 1560
    assert event["responding_ms"] == 2100
    assert event["partials"] == 3 and event["heard_chars"] == 47 and event["interruptions"] == 1
    # And nothing that could repeat what was said.
    assert "heard" not in event and "answer" not in event
    assert "orders" not in json.dumps(event)
