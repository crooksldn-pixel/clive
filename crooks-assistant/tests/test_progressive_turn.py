"""Progressive hydration through the real HTTP surface (D-5).

The unit tests in `test_progressive.py` hold the arithmetic. These hold the thing the owner
actually complained about: that the screen waited for the whole read graph. They drive /turn
over a real app with a DELIBERATELY SLOW source and poll /state beside it — which is what the
tablet does anyway, every 400 ms, to say CHECKING SHOPIFY — and assert the ORDERING: a card
the owner could read arrived while the turn was still running, not with it.

`turn_c8eb4cffe077` is the turn this is about: 7,975 ms to first cards, nothing on the glass
until the last read landed, and the owner saying the system "waits and then dumps a large
chunk".

7 October 2026 (DEC-068) reversed the half of this that put a read's cards on the glass while
the turn ran. The owner: "sometimes you'll get shown irrelevant screens that just happened
during a search process" — so a turn's workspace is QUIET, the tablet says what CLIVE is doing
in words while it works, and the cards come with the answer and are only what it is about.
The assertions below that pinned mid-turn cards now pin the opposite, each one marked; the
rest — one card drawn once, a cursor that repeats nothing, a log that keeps shapes — hold as
they were.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import progressive


@pytest.fixture(autouse=True)
def _clean_workspaces():
    progressive.reset()
    yield
    progressive.reset()


@pytest.fixture()
async def slow(monkeypatch):
    """A real app whose customer read takes half a second. Everything else is instant, so the
    order itself is knowable long before the turn can end."""
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.main import app
    from app.providers import max_agent_sdk
    from app.providers.base import TurnResult
    from app.session.manager import SessionManager
    from app.tools import shopify_tools
    from tests.test_context import Store, inbox

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", lambda self: (True, "fake scribe"))
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))

    class Provider:
        async def start(self): pass
        async def stop(self): pass
        async def health(self): return True, "fake"
        async def reset_session(self, session_id): pass
        async def set_system_prompt(self, prompt): pass
        async def interrupt(self, session_id): return True

        async def turn(self, session_id, text):
            # Claude, as far as the route is concerned: every sentence is the model's, and it
            # reads the order it was asked about through the gate, one call after another, so
            # the cards reach the glass as each read lands.
            from app.tools.dispatch import dispatch

            session = runtime.sessions.get_or_create(session_id)
            calls: list = []
            await dispatch("shopify_find_order", {"query": "1938"}, session=session, timeout_s=5, calls=calls)
            found = ((calls[-1].result or {}).get("orders") or [{}])[0] if calls and calls[-1].ok else {}
            await dispatch("shopify_order_detail", {"order_id": found.get("order_id") or ""}, session=session,
                           timeout_s=5, calls=calls)
            return TurnResult(text="the model answered", tool_calls=calls, session_id=session_id)

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = Provider()
        runtime.sessions = SessionManager()
        store = Store(delay_customer_s=0.5)
        runtime.shopify = store
        shopify_tools.bind(store, threads_for=inbox(delay_s=0.5))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            client.runtime = runtime
            yield client


async def test_no_card_reaches_the_glass_while_the_turn_is_still_running(slow):
    """The assertion is on the ORDER OF EVENTS, not the end state. DEC-068 (7 Oct) turned it
    round: while the reads run the poll carries what CLIVE is doing, in words, and no card at
    all; the order's card arrives with the answer. (Until 7 Oct this asserted the opposite —
    a readable card on the glass before /turn answered — as
    `test_a_card_the_owner_can_read_arrives_while_the_turn_is_still_running`.)"""
    turn = asyncio.create_task(slow.post("/turn", json={"text": "show me order 1938", "session_id": "prog"}))
    cursor = 0
    early: list[str] = []
    running = 0
    while not turn.done():
        await asyncio.sleep(0.02)
        state = (await slow.get(f"/state/prog?since={cursor}")).json()
        workspace = state.get("workspace")
        if not workspace:
            continue
        cursor = max(cursor, workspace["revision"])
        if not workspace["complete"]:
            running += 1
            early += [f"{patch['op']}:{patch['type']}" for patch in workspace["patches"]]
    response = await turn
    assert response.status_code == 200, response.text

    assert running, "the poll never saw the turn running, so this proved nothing"
    assert early == [], f"a search in progress took the screen: {early}"
    # And the answer's own card is the order, drawn with the answer.
    added = [p for p in response.json()["workspace"]["patches"] if p["op"] == "add"]
    assert any(p["type"] == "order" and not ((p.get("item") or {}).get("data") or {}).get("shell") for p in added), added


async def test_the_turn_reports_the_four_numbers_the_brief_asks_for(slow):
    body = (await slow.post("/turn", json={"text": "show me order 1938", "session_id": "prog"})).json()
    performance = body["performance"]
    # §15's four, renamed in Phase 5 to say what they measure (app/progressive.py TIMINGS).
    # Read from that tuple rather than repeated here, so a later rename cannot leave a turn
    # reporting one set of numbers and its own test asserting another.
    for name in progressive.TIMINGS:
        assert isinstance(performance[name], (int, float)), f"{name} was not measured"
    # The three the Mac already measured are still there, and still mean what they meant.
    for name in ("facts_ms", "workspace_ms", "prose_wait_ms"):
        assert name in performance
    assert performance["time_to_visible_shell"] <= performance["time_to_first_meaningful_fact"]
    assert performance["time_to_first_meaningful_fact"] <= performance["time_to_complete_workspace"]
    # DEC-068: nothing the owner can act on reaches the glass before the answer does, however
    # slow this turn's customer read is. (Until 7 Oct: `<`, the screen useful before complete.)
    assert performance["time_to_first_actionable_surface"] == performance["time_to_complete_workspace"]


async def test_the_four_numbers_are_held_and_not_merely_reported(slow):
    """§15: instrument AND HOLD. A number nobody asserts on is a number that drifts.

    Measured on this turn, whose customer read is deliberately half a second. Until 7 Oct the
    identity had to be on the glass within 50 ms and something actionable within half the
    turn; DEC-068 holds the opposite — the words say what CLIVE is doing while it reads, and
    the identity, the first fact and the first surface are the answer's, at the same moment.
    """
    body = (await slow.post("/turn", json={"text": "show me order 1938", "session_id": "prog"})).json()
    performance = body["performance"]
    assert performance["time_to_visible_shell"] == performance["time_to_complete_workspace"], performance
    assert performance["time_to_first_actionable_surface"] == performance["time_to_complete_workspace"], performance
    # And the workspace the tablet is polling says the same, in §27's words.
    state = (await slow.get("/state/prog")).json()["workspace"]
    assert state["state"] in progressive.STATES
    assert state["timings_ms"]["time_to_visible_shell"] == performance["time_to_visible_shell"]


async def test_the_identical_card_is_not_drawn_twice_and_the_repeat_is_counted(slow):
    """D-13 through the whole stack. Until 7 Oct the order was read progressively and
    presented again at the end, and the second render was counted, not drawn. DEC-068: nothing
    is staged while the reads run, so every card of the answer is drawn exactly once and there
    is no repeat to suppress."""
    body = (await slow.post("/turn", json={"text": "show me order 1938", "session_id": "prog"})).json()
    renders = body["performance"]["renders"]
    assert renders and renders.get("drawn"), renders
    # Nothing was staged before the answer, so nothing was staged twice. (Until 7 Oct:
    # `suppressed >= 1`, the progressive card and the answer's being the same card.)
    assert renders.get("suppressed", 0) == 0, f"a card was staged before the answer: {renders}"
    # And the patch log proves it: no identity is added twice, whatever the turn did.
    patches = (await slow.get("/state/prog")).json()["workspace"]["patches"]
    added = [p["id"] for p in patches if p["op"] == "add"]
    assert len(added) == len(set(added)), f"an identity was drawn from scratch twice: {added}"
    # Every card on the final screen is an identity the glass was told about.
    from app.render import render_id

    told = {p["id"] for p in patches if p["op"] in ("add", "data", "visual")}
    for item in body["ui"]:
        if item["type"] == "context_stack":
            continue
        assert render_id(item) in told, f"{item['type']} reached the payload and never the glass"


async def test_the_state_poll_carries_a_cursor_and_repeats_nothing(slow):
    await slow.post("/turn", json={"text": "show me order 1938", "session_id": "prog"})
    first = (await slow.get("/state/prog")).json()["workspace"]
    assert first and first["complete"] is True and first["patches"]
    again = (await slow.get(f"/state/prog?since={first['revision']}")).json()["workspace"]
    assert again["patches"] == [], "a tablet that is up to date is given nothing to redraw"


async def test_the_turn_log_keeps_the_shape_of_the_patches_and_not_their_contents(slow):
    """The patches carry the cards again — a customer's name, an address, an email body — and
    the turn log is read later, by a person, and may be handed to somebody else. It keeps
    which card changed and nothing that was on it, exactly as it does for `ui`."""
    import json

    body = (await slow.post("/turn", json={"text": "show me order 1938", "session_id": "prog"})).json()
    assert body["workspace"]["patches"], "the payload the tablet gets carries the cards themselves"
    assert any("item" in p for p in body["workspace"]["patches"])
    logged = json.loads(slow.runtime.turnlog.path.read_text(encoding="utf-8").strip().splitlines()[-1])["workspace"]
    assert all(isinstance(p, str) and ":" in p for p in logged["patches"]), logged["patches"]
    # (Until 7 Oct `renders["suppressed"] >= 1`. DEC-068 stages nothing before the answer, so the
    # value this moved to is exactly 0, as the response itself says above. The counts are a
    # Counter, which leaves a zero out, so an absent key is that 0.)
    assert logged["renders"].get("suppressed", 0) == 0 and logged["timings_ms"]["time_to_visible_shell"] is not None
    # A separate check, new with DEC-068: the answer's own card was drawn.
    assert logged["renders"]["drawn"] >= 1
    # And nothing a card said reaches the file through this key.
    assert "order_number" not in json.dumps(logged)


async def test_a_session_with_no_turn_in_flight_has_no_workspace(slow):
    body = (await slow.get("/state/nobody")).json()
    assert body["known"] is False
    assert body.get("workspace") in (None, {}), body
