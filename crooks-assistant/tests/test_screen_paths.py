"""Who can reach the owner's screens, and what a screen can have, end to end through the real
app (the round-9 deploy review: B-01-B-05-PATH, the server's half of NEW-B-LOCAL-SLIP, and
F-A3B-SCREEN-EVIDENCE).

Nothing here stands in for the owner rule. Every request goes through app.main's middleware
(guard_and_freshness), the real proxy_state and principal_verdict in app/routes/actions.py and
the screens router's own require_principal; every tool call goes the way the Agent SDK makes it
— the in-process MCP server (app/tools/registry.py build_mcp_server), the provider's _dispatch
(app/providers/max_agent_sdk.py) under the authority the turn's own request was granted, then
the dispatcher and the gate (app/tools/dispatch.py, app/tools/gate.py) — to the tool itself.
What stands in: the model, which makes the tool calls it is scripted to; and the kernel's and
Tailscale's own answers about who opened a connection and whose device an address is, with
production's switches — CROOKS_TAILSCALE_VERIFY on, the server itself not the owner — as
tests/test_proxy_identity.py does.
"""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import httpx
import pytest

from app import identity
from app.displays import store as store_module
from app.displays import views
from app.displays.store import SHOWING_KEEP_S
from app.main import app
from app.providers.base import TurnResult
from app.routes import displays as displays_route
from app.session.manager import SessionManager
from app.tools import authority as tool_authority
from app.tools import registry
from tests.test_displays import ORDER, Clock, FakeHydrator, Tick, handed_key, pair

OWNER = "owner@example.com"
MINE = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.9"}
# Tailscale says 100.64.0.3 is someone else's device.
STRANGER = {"Tailscale-User-Login": "someone@example.com", "X-Forwarded-For": "100.64.0.3"}
LYING = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.3"}
NO_LOGIN = {"X-Forwarded-For": "100.64.0.9"}
# A customer's details on a slip, and a phone for it.
SLIP = {**ORDER, "shipping_address": {**ORDER["shipping_address"], "phone": "07700 900123"}}
CUSTOMER = ("Sam Carter", "E8 1AA", "Sample Road", "07700 900123", "gift", "HW-TEE")
# What the owner said in a turn: a conversation's words, which no screen route ever reads.
SPOKEN = "tell me quietly about the Harlow warehouse lease"


class ScriptedModel:
    """The model, scripted: on each turn it makes the tool calls it was given, exactly as the
    Agent SDK calls CLIVE's tools back — through the in-process MCP server built from the
    registry, into the real provider's _dispatch, under the authority the turn's request held
    when the turn began (MaxAgentSDKProvider._turn_locked) — and answers with what they said."""

    def __init__(self, runtime) -> None:
        from app.providers.max_agent_sdk import MaxAgentSDKProvider, _Holder

        self.runtime = runtime
        self.provider = MaxAgentSDKProvider(system_prompt="", tool_timeout_s=5)
        self.holder = _Holder()
        self.server = registry.build_mcp_server(lambda name, args: self.provider._dispatch(name, args, holder=self.holder))
        self.script: list[tuple[str, dict]] = []
        self.turns = 0
        self.said: list[str] = []

    async def start(self): pass
    async def stop(self): pass
    async def health(self): return True, "scripted"
    async def reset_session(self, session_id): pass
    async def set_system_prompt(self, prompt): pass
    async def interrupt(self, session_id): return True

    async def turn(self, session_id, text):
        from app.providers.max_agent_sdk import _Conversation

        self.turns += 1
        session = self.runtime.sessions.get(session_id)
        conv = _Conversation(key=session_id, session_id=session_id, branch_id="", client=None, holder=self.holder)
        self.holder.conversation = conv
        conv.begin(session, authority=tool_authority.current())
        entry = self.server["instance"].get_request_handler("tools/call")
        said = []
        try:
            for name, args in self.script:
                result = await entry.handler(None, entry.params_type(name=name, arguments=args))
                said.append(result.content[0].text)
        finally:
            conv.running = False
        self.said.extend(said)
        return TurnResult(text=" | ".join(said) or "nothing to do", session_id=session_id)


@pytest.fixture()
async def world(tmp_path, monkeypatch):
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    async def scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.sessions = SessionManager()
        runtime.provider = ScriptedModel(runtime)
        # Production's switches: the owner's login on the list, Tailscale asked about every
        # forwarded request, and a request made on the server itself not the owner's.
        runtime.settings = runtime.settings.model_copy(update={
            "allowed_logins": OWNER, "tailscale_verify": True, "local_owner": False, "writes_local_owner": False})
        app.state.allowed_logins = runtime.allowed_logins
        identity.bind_peer_check(lambda client, server: (True, "opened by tailscaled (pid 1)"))
        identity.bind_self_check(lambda address: False)
        identity.bind_runner(lambda cli, address: {"UserProfile": {"LoginName": OWNER if address == "100.64.0.9" else "someone@example.com"}})
        monkeypatch.setattr(identity, "cli_path", lambda configured="": "/usr/bin/tailscale")
        screens = store_module.install(tmp_path / "objectives" / "displays.json", mono=Tick())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://t") as client:
            yield SimpleNamespace(client=client, runtime=runtime, model=runtime.provider, screens=screens)


def refused_callers():
    """Every caller the owner rule refuses, and what each is: (name, headers, kernel says the
    connection came through tailscaled)."""
    return (
        ("a forged forwarding header", MINE, False),
        ("no Tailscale login", NO_LOGIN, True),
        ("a stranger's login", STRANGER, True),
        ("his login on someone else's device", LYING, True),
        ("the server itself", {}, True),
    )


def _through(peer: bool):
    identity.bind_peer_check(lambda client, server: (True, "opened by tailscaled (pid 1)") if peer
                             else (False, "the connection was opened by something other than tailscaled"))


def _every_screen_route(sid: str) -> list[tuple[str, str, dict | None]]:
    """Every route the screens router serves, with a body that would act if it were let in, so
    a route added later is walked too (or this fails)."""
    bodies = {
        "/displays/register": {"name": "Kitchen screen"},
        "/displays/forget": {"name": "Packing screen"},
        "/displays/{screen_id}/seen": {"version": 1, "start": 0, "end": 1},
        "/displays/{screen_id}/done": {"version": 1, "confirm": True},
        "/displays/{screen_id}/video": {"pane": 0, "version": 1, "state": "playing", "at": 1.0},
        "/displays/{screen_id}/remote/tick": {"pane": 0, "item": 0, "packed": True, "version": 1},
        "/displays/{screen_id}/remote/page": {"pane": 0, "delta": 1, "version": 1},
        "/displays/{screen_id}/remote/done": {"pane": 0, "version": 1},
        "/displays/{screen_id}/remote/video": {"pane": 0, "version": 1, "action": "pause"},
        "/displays/{screen_id}/remote/again": {"pane": 0, "version": 1},
        "/displays/{screen_id}/remote/off": {"screen_version": 1},
        # Round 12: the owner's hand, an order held and dropped on the screen (web/lift.js).
        "/displays/{screen_id}/show": {"session_id": "s1", "kind": "order", "ref": "gid://shopify/Order/1938"},
    }
    out = []
    for route in displays_route.router.routes:
        for method in sorted(route.methods - {"HEAD"}):
            body = bodies.get(route.path) if method == "POST" else None
            assert method == "GET" or body is not None, f"a body for {route.path}"
            out.append((method, route.path.replace("{screen_id}", sid), body))
    assert len(out) >= 14
    return out


# --------------------------------------------------------------------------- B-01-B-05-PATH


async def test_a_refused_caller_reaches_no_screen_route_and_no_screen_tool(world, monkeypatch):
    """B-01-B-05-PATH (round 9, "cannot tell"): the route tests stood in for the owner rule and
    the tool tests called dispatch directly, so whether a refused caller could reach a screen on
    the production path was unverified. Here, through the real app: a forged forwarding header,
    a proxied request with no login, a stranger's login, the owner's login from a device
    Tailscale says is someone else's, and the server itself, are each refused every screen
    route (with a body that would act) and /turn — so the model is never asked and no screen
    tool runs — and the record does not move by a byte. Even the screen's own key, stolen, is
    nothing to them. The owner's own device, through the same doors, is answered."""
    screens = world.screens
    screen = pair(screens, "Packing screen")
    sid, key = screen["id"], screen["screen_key"]
    screens.show(sid, views.order_view(SLIP))
    before = screens.path.read_bytes()
    world.model.script = [("screen_show", {"screen": "Packing screen", "clear": True}),
                          ("screen_off", {"screen": "Packing screen"}), ("screen_list", {})]
    for who, headers, peer in refused_callers():
        _through(peer)
        for method, path, body in _every_screen_route(sid):
            for extra in ({}, {"Cookie": f"clive_screen={key}"}):
                answer = await world.client.request(method, path, json=body, headers={**headers, **extra})
                assert answer.status_code == 403, (who, method, path, answer.status_code)
                for word in CUSTOMER:
                    assert word not in answer.text, (who, path, word)
        turned = await world.client.post("/turn", json={"text": "clear the packing screen"}, headers=headers)
        assert turned.status_code == 403, (who, turned.status_code)
    assert world.model.turns == 0, "the model was never asked, so no tool was called"
    assert screens.path.read_bytes() == before and not screens.journal_path.exists()
    # The owner's own device, through the same doors, is answered, and the tools run for him.
    _through(True)
    polled = await world.client.get(f"/displays/{sid}?v=-1", headers={**MINE, "Cookie": f"clive_screen={key}"})
    assert polled.status_code == 200 and polled.json()["showing"]["order"]["customer"] == "Sam Carter"
    turned = await world.client.post("/turn", json={"text": "clear the packing screen"}, headers=MINE)
    assert turned.status_code == 200 and world.model.turns == 1
    assert screens.poll(sid, key)["showing"] is None, "cleared, by the owner's own request"


async def test_screen_show_puts_up_only_an_order_this_conversation_was_issued(world, monkeypatch):
    """B-05 on the production path (round 9, B-01-B-05-PATH): an order id the conversation was
    not issued is refused by the gate before the tool runs — no order is read, nothing goes on
    the screen — even for the owner's own request; once the conversation has looked it up (it
    is issued, as an order lookup does), the same call puts the slip up."""
    from app.tools import shopify_tools

    hydrator = FakeHydrator()
    monkeypatch.setattr(shopify_tools, "_hydrator", hydrator)
    screens = world.screens
    screen = pair(screens, "Packing screen")
    oid = SLIP["order_id"]
    world.model.script = [("screen_show", {"screen": "Packing screen", "order_id": oid})]
    first = await world.client.post("/turn", json={"text": "put 1047 on the packing screen", "session_id": "s1"}, headers=MINE)
    assert first.status_code == 200
    assert world.model.said[-1].startswith("NOT YET") and "not an id this conversation has looked up" in world.model.said[-1]
    assert hydrator.asked == [] and screens.poll(screen["id"], screen["screen_key"])["showing"] is None
    for forged in ("gid://shopify/Order/9", "../../etc/passwd", "obj_0123abcd"):
        world.model.script = [("screen_show", {"screen": "Packing screen", "order_id": forged})]
        await world.client.post("/turn", json={"text": "put it up", "session_id": "s1"}, headers=MINE)
        assert world.model.said[-1].startswith(("NOT YET", "REFUSED")), world.model.said[-1]
    assert hydrator.asked == [] and screens.poll(screen["id"], screen["screen_key"])["showing"] is None
    world.runtime.sessions.get("s1").issue(oid)          # the conversation looked the order up
    world.model.script = [("screen_show", {"screen": "Packing screen", "order_id": oid})]
    shown = await world.client.post("/turn", json={"text": "put 1047 on the packing screen", "session_id": "s1"}, headers=MINE)
    assert shown.status_code == 200 and not world.model.said[-1].startswith(("NOT YET", "REFUSED", "ERROR"))
    assert hydrator.asked == [oid]
    assert screens.poll(screen["id"], screen["screen_key"])["showing"]["ref"] == oid
    # Another conversation was not issued it.
    world.model.script = [("screen_show", {"screen": "Packing screen", "order_id": oid})]
    await world.client.post("/turn", json={"text": "put 1047 up again", "session_id": "s2"}, headers=MINE)
    assert world.model.said[-1].startswith("NOT YET") and hydrator.asked == [oid]


# --------------------------------------------------------------------------- NEW-B-LOCAL-SLIP (the server's half)


async def test_a_screen_whose_device_is_refused_or_whose_slip_is_past_its_time_is_given_nothing(world, monkeypatch):
    """NEW-B-LOCAL-SLIP, the server's half (round 9, "cannot tell"; what the open page then does
    with it is web/display.js and tests/web/display.test.js). A screen showing a customer's slip
    whose login comes off the allow-list is answered 403 on its very next ask, with nothing of
    the slip; and a slip up longer than SHOWING_KEEP_S is taken down — on the next ask, and
    off the disk — whether or not the screen ever asks again."""
    screens = world.screens
    clock = Clock()
    screens.clock = clock
    monkeypatch.setattr(store_module, "_now_iso", lambda: dt.datetime.fromtimestamp(clock.now, dt.UTC).isoformat(timespec="seconds"))
    screen = pair(screens, "Packing screen")
    sid, key = screen["id"], screen["screen_key"]
    tv = {**MINE, "Cookie": f"clive_screen={key}"}
    screens.show(sid, views.order_view(SLIP))
    assert (await world.client.get(f"/displays/{sid}?v=-1", headers=tv)).json()["showing"]["kind"] == "order"
    # The owner takes his login off the list: the next ask is refused, and carries nothing.
    world.runtime.settings = world.runtime.settings.model_copy(update={"allowed_logins": "someone-else@example.com"})
    app.state.allowed_logins = world.runtime.allowed_logins
    refused = await world.client.get(f"/displays/{sid}?v=-1", headers=tv)
    assert refused.status_code == 403
    for word in CUSTOMER:
        assert word not in refused.text, word
    world.runtime.settings = world.runtime.settings.model_copy(update={"allowed_logins": OWNER})
    app.state.allowed_logins = world.runtime.allowed_logins
    # Past its time: taken down on the next ask, and off the disk.
    clock.now += SHOWING_KEEP_S - 60
    assert (await world.client.get(f"/displays/{sid}?v=-1", headers=tv)).json()["showing"]["kind"] == "order"
    clock.now += 120
    gone = (await world.client.get(f"/displays/{sid}?v=-1", headers=tv)).json()
    assert gone["showing"] is None and gone["beside"] is None
    for word in CUSTOMER:
        assert word not in screens.path.read_text(), word
    # And with the screen switched off, housekeeping's pass alone takes the next one down.
    from app.main import housekeep_once

    screens.show(sid, views.order_view(SLIP))
    clock.now += SHOWING_KEEP_S + 60
    assert housekeep_once(object()) == ""
    assert "Sam Carter" not in screens.path.read_text() and screens._data["screens"][sid]["showing"] is None


# --------------------------------------------------------------------------- F-A3B-SCREEN-EVIDENCE


async def test_what_an_approved_screen_can_have_from_every_screens_route(world, monkeypatch):
    """F-A3B-SCREEN-EVIDENCE (round 9, "cannot tell"): what a keyed TV actually receives from the
    screens' routes was not established. Here it is, route by route, for an approved screen on
    the owner's login holding its cookie, beside another screen showing a customer's slip, after
    a conversation in which the owner said things: with its cookie, its own record (the slip it
    shows, in full, is its own); from the owner's routes, what every device of his has — the
    list of screens and titles, the done record, and the remote's view, which carries an order's
    items and never who they go to; and nowhere another screen's slip, any key or hash or code,
    or a conversation's words. Its cookie opens no other screen's own routes."""
    screens = world.screens
    tv = pair(screens, "Office screen")
    other = pair(screens, "Packing screen")
    screens.show(tv["id"], views.list_view("Today", ["Steam the jackets"]))
    screens.show(other["id"], views.order_view(SLIP))
    screens.show(other["id"], views.video_view("dQw4w9WgXcQ", title="Heat"), beside=True)
    world.model.script = []
    assert (await world.client.post("/turn", json={"text": SPOKEN, "session_id": "s1"}, headers=MINE)).status_code == 200
    assert world.runtime.sessions.get("s1").heard == SPOKEN
    mine = {**MINE, "Cookie": f"clive_screen={tv['screen_key']}"}
    secrets = [tv["screen_key"], other["screen_key"], tv["code"], other["code"]]
    stored = json.loads(screens.path.read_text())["screens"]
    secrets += [x["secret"] for x in stored.values()]

    seen: dict[str, httpx.Response] = {}
    for method, path, _body in _every_screen_route(other["id"]) + _every_screen_route(tv["id"]):
        if method != "GET":
            continue                     # what can be READ; the acts are below
        answer = await world.client.request(method, path, headers=mine)
        seen[path] = answer
        for secret in secrets:
            assert secret not in answer.text, path
        assert SPOKEN not in answer.text and "Harlow" not in answer.text, path
    # Its own record, in full, by its cookie.
    own = seen[f"/displays/{tv['id']}"].json()
    assert set(own) == {"id", "name", "version", "showing", "beside", "pending", "now", "last_done"}
    assert own["showing"]["list"]["lines"] == ["Steam the jackets"] and own["pending"] is False
    # Another screen's own record: refused, with nothing in the answer.
    theirs = seen[f"/displays/{other['id']}"]
    assert theirs.status_code == 403 and set(theirs.json()) == {"code", "detail"}
    # The owner's routes: what every one of his devices has.
    listing = seen["/displays"].json()
    assert set(listing) == {"screens", "done"}
    assert all(set(x) == {"id", "name", "online", "showing", "since", "beside", "pending"} for x in listing["screens"])
    remote = seen[f"/displays/{other['id']}/remote"].json()
    assert set(remote) == {"id", "name", "online", "version", "now", "panes"}
    order, video = remote["panes"]
    assert set(order) == {"pane", "v", "kind", "title", "at", "done_at", "items", "partial", "page", "pages"}
    assert all(set(item) == {"i", "title", "variant", "quantity", "sent", "image", "ticked"} for item in order["items"])
    assert set(video) == {"pane", "v", "kind", "title", "at", "done_at", "video", "player", "playing"}
    for path, answer in seen.items():
        if path == f"/displays/{tv['id']}":
            continue                     # its own record is its own
        for word in CUSTOMER:
            assert word not in answer.text, (path, word)
    # Nothing it can do with its cookie on another screen's own routes.
    for path, body in ((f"/displays/{other['id']}/seen", {"version": 1, "start": 0, "end": 1}),
                       (f"/displays/{other['id']}/done", {"version": 1, "confirm": True}),
                       (f"/displays/{other['id']}/video", {"pane": 1, "version": 2, "state": "playing", "at": 1.0})):
        refused = await world.client.post(path, json=body, headers=mine)
        assert refused.status_code == 403 and refused.json()["code"] == "not_this_screen", path
    # Naming itself again hands it only a new cookie and its own name back.
    again = await world.client.post("/displays/register", json={"name": "Office screen"}, headers=mine)
    assert again.status_code == 200 and again.json() == {"id": tv["id"], "name": "Office screen", "pending": False}
    assert handed_key(again) not in again.text
