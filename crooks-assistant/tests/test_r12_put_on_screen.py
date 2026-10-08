"""Round 12: the owner holds an order or an objective and drops it on one of his screens — the
server's side (George, 29 September: "dragging an order, email, order card or objective by holding
and a 'displays screen appearing' which you can drag and drop the item to display too").

The page (web/lift.js) posts `POST /displays/{screen_id}/show` with the conversation the record
was held in and the record as its card carries it. Everything here goes through the real app: the
door (app/main.py, principal_verdict), the screens router's require_principal, the route, and then
the screen_show tool through the dispatcher and the gate (app/displays/put.py). What stands in is
the model (tests/test_screen_paths.py ScriptedModel), a Shopify client that answers like the store
(tests/test_context.py Store) and, where a read must fail or be slow, the order read itself.

What is held: an order this conversation was shown goes on the screen it was dropped on, as the
same slip the spoken request puts up, and the model is never asked; and a drop is refused — with
nothing read and nothing on the screen changed — for anyone but the owner, for a record this
conversation was not issued, for a screen that is gone or waiting for approval, for a body that
names anything but the conversation and the record, and for a conversation that has gone or is
another login's. The answer carries no customer's details. A drop made while a turn is in flight is
answered at once and leaves the turn's answer alone.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app.clients.shopify import ShopifyError
from app.displays import views
from app.tools import shopify_tools
from tests.test_context import ORDER, Store, inbox
from tests.test_displays import pair
from tests.test_screen_paths import (  # noqa: F401 (the fixture)
    MINE,
    _every_screen_route,
    _through,
    refused_callers,
    world,
)

# What the owner would not want on anything but the slip itself: the customer's name, address,
# email and the order's note (tests/test_context.py ORDER_NODE).
CUSTOMER = ("Daniel Stub", "Somewhere Street", "SL4 1AA", "daniel@example.com", "Leave with the neighbour", "Windsor")


@pytest.fixture()
def shop(monkeypatch):
    """A Shopify that answers like the store, bound as the app binds the real one."""
    monkeypatch.setattr(shopify_tools, "_client", shopify_tools._client)
    monkeypatch.setattr(shopify_tools, "_hydrator", shopify_tools._hydrator)
    store = Store()
    shopify_tools.bind(store, threads_for=inbox())
    return store


@pytest.fixture()
def goals(world, monkeypatch):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """CLIVE's own objectives, in this test's folder, put back as they were afterwards."""
    from app.objectives import store as objectives_module

    monkeypatch.setattr(objectives_module, "_STORE", None)
    return objectives_module.install(world.screens.path.parent / "goals")


async def looked_up(app, session_id: str = "s1") -> None:
    """The conversation asks for order 1938, and the lookup (not this test) issues its id."""
    app.model.script = [("shopify_find_order", {"query": "1938"})]
    answer = await app.client.post("/turn", json={"text": "find order 1938", "session_id": session_id}, headers=MINE)
    assert answer.status_code == 200
    assert ORDER in app.runtime.sessions.get(session_id).issued_ids, "issued by the lookup itself"


async def drop(app, screen_id: str, *, headers=None, **body):
    """The page's drop, as web/lift.js posts it."""
    payload = {"session_id": "s1", "kind": "order", "ref": ORDER, **body}
    return await app.client.post(f"/displays/{screen_id}/show", json=payload, headers=MINE if headers is None else headers)


def showing(screens, tv):
    now = screens.poll(tv["id"], tv["screen_key"])
    return now["showing"], now["beside"]


# --------------------------------------------------------------------------- the reproduction


async def test_an_order_he_was_shown_and_drops_on_a_screen_goes_up_there(world, shop):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """George's request, as the drop reaches the server: he asked for order 1938, it was drawn,
    he held it and let go over the Office TV. The Office TV is given the order's slip on its next
    ask; the answer says what it shows now and whether it is on; the model is never asked. On the
    code before round 12 there is no such route and nothing goes up."""
    screens = world.screens
    tv = pair(screens, "Office TV")
    await looked_up(world)
    turns = world.model.turns
    answer = await drop(world, tv["id"])
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"ok": True, "screen": "Office TV", "screen_id": tv["id"], "showing": "Order CROOKS-1938",
                             "on": True}
    assert world.model.turns == turns, "a drop is a tap: no model is asked"
    up, beside = showing(screens, tv)
    assert up["kind"] == "order" and up["ref"] == ORDER and beside is None
    assert up["order"]["customer"] == "Daniel Stub" and up["order"]["items"][0]["title"] == "Yard Jeans"
    # The TV itself, with its own cookie, through the door.
    polled = await world.client.get(f"/displays/{tv['id']}?v=-1", headers={**MINE, "Cookie": f"clive_screen={tv['screen_key']}"})
    assert polled.status_code == 200 and polled.json()["showing"]["ref"] == ORDER


async def test_the_drop_puts_up_exactly_the_slip_his_spoken_request_puts_up(world, shop):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """Not a parallel path: the same tool builds the same slip from the same record, with the fields
    a screen may carry and no others. The pane a drop puts on one screen and the pane "put 1938 on
    the packing screen" puts on another are the same, but for when and at which version."""
    screens = world.screens
    office, packing = pair(screens, "Office TV"), pair(screens, "Packing screen")
    await looked_up(world)
    assert (await drop(world, office["id"])).status_code == 200
    world.model.script = [("screen_show", {"screen": "Packing screen", "order_id": ORDER})]
    await world.client.post("/turn", json={"text": "put 1938 on the packing screen", "session_id": "s1"}, headers=MINE)
    dropped, spoken = showing(screens, office)[0], showing(screens, packing)[0]
    for pane in (dropped, spoken):
        pane.pop("at"), pane.pop("v")
    assert dropped == spoken and dropped["by"] == "clive"


# --------------------------------------------------------------------------- refused at the door


async def test_nobody_but_the_owner_reaches_the_drop(world, shop):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """Every caller the owner rule refuses — a forged forwarding header, no login, a stranger, his
    login on someone else's device, the server itself — is refused the drop at the door with a body
    that would act, the TV's own cookie or not: nothing is read and the screen does not change. And
    the route is one of the screens router's, so tests/test_screen_paths.py walks it too."""
    screens = world.screens
    tv = pair(screens, "Office TV")
    await looked_up(world)
    reads, record = len(shop.queries), screens.path.read_bytes()
    assert any(path == f"/displays/{tv['id']}/show" for _, path, _ in _every_screen_route(tv["id"]))
    for who, headers, peer in refused_callers():
        _through(peer)
        for extra in ({}, {"Cookie": f"clive_screen={tv['screen_key']}"}):
            answer = await drop(world, tv["id"], headers={**headers, **extra})
            assert answer.status_code == 403, (who, answer.status_code)
            for word in CUSTOMER:
                assert word not in answer.text, (who, word)
    _through(True)
    assert len(shop.queries) == reads and screens.path.read_bytes() == record
    assert showing(screens, tv) == (None, None)


# --------------------------------------------------------------------------- the issued-id rule


async def test_a_record_this_conversation_was_not_issued_is_refused_before_anything_is_read(world, shop):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """The gate's rule, at the server and not only in the page: an order this conversation never
    looked up is refused (403, not_issued) before Shopify is asked — even when another conversation
    of his did look it up — and so is an id of the wrong kind, an invented one, and an order named
    as an objective. Nothing goes on the screen."""
    screens = world.screens
    tv = pair(screens, "Office TV")
    world.runtime.sessions.get_or_create("s1")
    first = await drop(world, tv["id"])
    assert first.status_code == 403 and first.json()["code"] == "not_issued", first.text
    assert "wasn't shown in this conversation" in first.json()["detail"]
    assert shop.queries == [], "refused before the order was read"
    await looked_up(world, "s2")                         # another conversation was shown it
    reads = len(shop.queries)
    assert (await drop(world, tv["id"])).json()["code"] == "not_issued"
    for kind, ref in (("order", "gid://shopify/Customer/7"), ("order", "gid://shopify/Order/9"), ("order", "obj_0123abcd"),
                      ("objective", ORDER), ("objective", "obj_0123abcd"), ("order", "../../etc/passwd")):
        refused = await drop(world, tv["id"], kind=kind, ref=ref)
        assert refused.status_code == 403 and refused.json()["code"] == "not_issued", (kind, ref, refused.text)
    assert len(shop.queries) == reads and showing(screens, tv) == (None, None)


# --------------------------------------------------------------------------- the screen


async def test_a_screen_that_is_gone_unknown_or_waiting_for_approval_is_refused(world, shop):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """Only one of his approved screens takes a drop: an id that is no screen, one that is not an
    id, a screen he has removed (404, not_found), and one still showing its code (409,
    not_approved, in words that say what to do) — each refused before the order is read."""
    screens = world.screens
    await looked_up(world)
    reads = len(shop.queries)
    for missing in ("scr_000000000000", "not-a-screen"):
        answer = await drop(world, missing)
        assert answer.status_code == 404 and answer.json()["code"] == "not_found", (missing, answer.text)
    waiting = screens.register("Bedroom TV")
    answer = await drop(world, waiting["id"])
    assert answer.status_code == 409 and answer.json()["code"] == "not_approved"
    assert answer.json()["detail"] == "The Bedroom TV hasn't been approved yet. Tell CLIVE the code it shows, then try again."
    gone = pair(screens, "Kitchen TV")
    screens.forget(gone["id"])
    assert (await drop(world, gone["id"])).status_code == 404
    assert len(shop.queries) == reads
    assert screens.poll(waiting["id"], waiting["screen_key"])["showing"] is None


# --------------------------------------------------------------------------- the body


async def test_the_body_names_the_conversation_and_the_record_and_nothing_else(world, shop):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """What a screen shows is built from CLIVE's own record, never from the page: a title, lines,
    clear, beside or another screen's name in the body is refused (422), and so is a kind a screen
    has no view for — an email, a customer, a list."""
    screens = world.screens
    tv = pair(screens, "Office TV")
    await looked_up(world)
    reads = len(shop.queries)
    for extra in ({"title": "Wages"}, {"lines": ["a"]}, {"clear": True}, {"beside": True}, {"screen": "Office TV"}):
        answer = await drop(world, tv["id"], **extra)
        assert answer.status_code == 422, extra
    for kind in ("email_thread", "customer", "list", "video"):
        assert (await drop(world, tv["id"], kind=kind)).status_code == 422, kind
    for body in ({"kind": "order", "ref": ORDER}, {"session_id": "s1", "kind": "order"}, {"session_id": "s1", "kind": "order", "ref": ""}):
        answer = await world.client.post(f"/displays/{tv['id']}/show", json=body, headers=MINE)
        assert answer.status_code == 422, body
    assert len(shop.queries) == reads and showing(screens, tv) == (None, None)


# --------------------------------------------------------------------------- the conversation


async def test_a_conversation_that_has_gone_or_is_another_logins_is_refused(world, shop):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """The conversation is his, as on every route that takes one: one CLIVE has let go of is
    refused in words that say what to do (409, no_session), and one bound to another login is
    refused (403) even when that conversation was shown the order."""
    screens = world.screens
    tv = pair(screens, "Office TV")
    gone = await drop(world, tv["id"], session_id="never-made")
    assert gone.status_code == 409 and gone.json()["code"] == "no_session"
    assert gone.json()["detail"] == "CLIVE has let go of that conversation. Ask for it again, then hold it."
    theirs = world.runtime.sessions.get_or_create("theirs")
    theirs.login = "someone@example.com"
    theirs.issue(ORDER)
    answer = await drop(world, tv["id"], session_id="theirs")
    assert answer.status_code == 403 and answer.json()["code"] == "wrong_session"
    assert shop.queries == [] and showing(screens, tv) == (None, None)


# --------------------------------------------------------------------------- privacy


async def test_what_a_drop_answers_and_writes_to_the_log_carries_no_customers_details(world, shop, caplog):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """The screen is given the slip, as a slip is (the screen_show tool's rule); nothing else is.
    The drop's answer is the screen's name, the title of what it shows and whether it is on; the
    owner's list of screens and the remote's view carry no customer's details either; and nothing
    the drop logs does. CROOKS_SCREEN_SNAPSHOTS is off, as production has it, and the drop does not
    ask for a copy of any screen."""
    assert world.runtime.settings.screen_snapshots is False
    screens = world.screens
    tv = pair(screens, "Office TV")
    await looked_up(world)
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        answer = await drop(world, tv["id"])
    assert answer.status_code == 200
    listed = await world.client.get("/displays", headers=MINE)
    remote = await world.client.get(f"/displays/{tv['id']}/remote", headers=MINE)
    logged = "\n".join(record.getMessage() for record in caplog.records)
    for word in CUSTOMER:
        assert word not in answer.text and word not in listed.text and word not in remote.text, word
        assert word not in logged, word
    assert showing(screens, tv)[0]["order"]["customer"] == "Daniel Stub", "the slip is the slip"


# --------------------------------------------------------------------------- objectives


async def test_an_objective_on_his_home_can_be_dropped_on_a_screen_and_only_that_conversations(world, goals):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """The home lists his objectives with the conversation its page is in (GET /objectives with
    session_id), and each one listed is shown to that conversation: dropped, it goes up as the
    objective view. A conversation the home never listed them to is refused (403), and so is a
    listing asked with a conversation that is another login's — nothing is issued into it."""
    made = goals.create(title="Autumn drop shoot", request="Get the autumn drop shot by Friday", by="owner")
    screens = world.screens
    tv = pair(screens, "Office TV")
    listed = await world.client.get("/objectives", params={"session_id": "s1"}, headers=MINE)
    assert listed.status_code == 200 and [o["id"] for o in listed.json()["objectives"]] == [made.id]
    answer = await drop(world, tv["id"], kind="objective", ref=made.id)
    assert answer.status_code == 200, answer.text
    assert answer.json()["showing"] == "Autumn drop shoot"
    assert showing(screens, tv)[0]["kind"] == "objective" and showing(screens, tv)[0]["ref"] == made.id
    world.runtime.sessions.get_or_create("s2")
    refused = await drop(world, tv["id"], session_id="s2", kind="objective", ref=made.id)
    assert refused.status_code == 403 and refused.json()["code"] == "not_issued"
    theirs = world.runtime.sessions.get_or_create("theirs")
    theirs.login = "someone@example.com"
    assert (await world.client.get("/objectives", params={"session_id": "theirs"}, headers=MINE)).status_code == 200
    assert made.id not in theirs.issued_ids
    # Listed without a conversation, as before round 12: nothing is issued anywhere.
    before = {sid: set(world.runtime.sessions.get(sid).issued_ids) for sid in ("s1", "s2")}
    assert (await world.client.get("/objectives", headers=MINE)).status_code == 200
    assert {sid: set(world.runtime.sessions.get(sid).issued_ids) for sid in ("s1", "s2")} == before


async def test_the_home_asking_again_and_again_does_not_keep_a_conversation_open(world, goals):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """The home asks every twenty seconds. A conversation it finds is issued to without being
    touched, so it still closes when it would have; one that is not there is made, as opening the
    page makes it."""
    goals.create(title="Restock the black caps", request="Restock black caps", by="owner")
    runtime = world.runtime
    session = runtime.sessions.get_or_create("s1")
    session.last_seen_at -= 600
    seen = session.last_seen_at
    await world.client.get("/objectives", params={"session_id": "s1"}, headers=MINE)
    assert runtime.sessions.peek("s1").last_seen_at == seen
    await world.client.get("/objectives", params={"session_id": "fresh"}, headers=MINE)
    assert runtime.sessions.exists("fresh")


# --------------------------------------------------------------------------- a real day


class SlowOrFailing:
    """The order read, standing in for a Shopify that fails or does not answer in time."""

    def __init__(self, *, fail: str = "", wait_s: float = 0.0) -> None:
        self.fail, self.wait_s, self.asked = fail, wait_s, []

    async def order(self, order_id: str, **_):
        self.asked.append(order_id)
        if self.wait_s:
            await asyncio.sleep(self.wait_s)
        raise ShopifyError(self.fail or "Shopify did not answer.")


async def test_a_failed_or_slow_shopify_read_puts_nothing_up_and_says_why(world, shop, monkeypatch):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """A Shopify that fails is said in its own words; one that does not answer within the tool's
    time is said plainly — never "screen_show did not respond". Nothing goes on the screen, and what
    it showed stays."""
    screens = world.screens
    tv = pair(screens, "Office TV")
    screens.show(tv["id"], views.list_view("Today", ["Steam the jackets"]))
    await looked_up(world)
    monkeypatch.setattr(shopify_tools, "_hydrator", SlowOrFailing(fail="Shopify is not answering just now."))
    failed = await drop(world, tv["id"])
    assert failed.status_code == 409 and failed.json() == {"code": "not_shown", "detail": "Shopify is not answering just now."}
    world.runtime.settings = world.runtime.settings.model_copy(update={"tool_timeout_s": 0.2})
    monkeypatch.setattr(shopify_tools, "_hydrator", SlowOrFailing(wait_s=5))
    slow = await drop(world, tv["id"])
    assert slow.status_code == 409
    assert slow.json()["detail"] == "That took too long to read, so nothing went on the Office TV. Try again."
    assert showing(screens, tv)[0]["title"] == "Today", "what it showed stays"


async def test_a_drop_during_a_turn_is_answered_at_once_and_leaves_the_turn_alone(world, shop, monkeypatch):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """He holds an order while CLIVE is still answering him. The drop does not wait for the turn,
    and the turn's answer is its own: no card and no word of the drop in it."""
    screens = world.screens
    tv = pair(screens, "Office TV")
    await looked_up(world)
    real = shopify_tools._hydrator
    release = asyncio.Event()

    class Held:
        """The turn's own read waits until the drop has been answered; the drop's read does not."""

        calls = 0

        async def order(self, order_id, **kwargs):
            Held.calls += 1
            if Held.calls == 1:
                await release.wait()
            return await real.order(order_id, **kwargs)

    monkeypatch.setattr(shopify_tools, "_hydrator", Held())
    world.model.script = [("shopify_order_detail", {"order_id": ORDER})]
    turn = asyncio.create_task(world.client.post("/turn", json={"text": "open 1938", "session_id": "s1"}, headers=MINE))
    for _ in range(200):
        if Held.calls:
            break
        await asyncio.sleep(0.01)
    assert Held.calls == 1 and not turn.done(), "the turn is in flight"
    dropped = await asyncio.wait_for(drop(world, tv["id"]), timeout=5)
    assert dropped.status_code == 200 and not turn.done()
    release.set()
    answered = (await asyncio.wait_for(turn, timeout=10)).json()
    assert "Office TV" not in json.dumps(answered.get("ui") or []) and "Office TV" not in str(answered.get("answer"))
    assert showing(screens, tv)[0]["ref"] == ORDER


async def test_dropping_again_or_onto_a_screen_showing_two_things_puts_this_up_in_their_place(world, shop):  # noqa: F811 - the fixture is tests/test_screen_paths.py world
    """A drop is "put this on that screen": dropped again it goes up again, and on a screen showing
    two things it takes the whole screen, as the spoken request without "beside" does. The answer
    names what is up now."""
    screens = world.screens
    tv = pair(screens, "Office TV")
    await looked_up(world)
    assert (await drop(world, tv["id"])).status_code == 200
    first = screens.poll(tv["id"], tv["screen_key"])["version"]
    assert (await drop(world, tv["id"])).status_code == 200
    assert screens.poll(tv["id"], tv["screen_key"])["version"] > first
    screens.show(tv["id"], views.list_view("Today", ["Steam the jackets"]))
    screens.show(tv["id"], views.list_view("Tomorrow", ["Press the tees"]), beside=True)
    answer = await drop(world, tv["id"])
    assert answer.status_code == 200 and answer.json()["showing"] == "Order CROOKS-1938"
    assert showing(screens, tv)[0]["ref"] == ORDER and showing(screens, tv)[1] is None

