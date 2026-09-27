"""The owner's screens: a device names itself at /display, the owner approves it with the code
it shows, CLIVE puts an order's slip, an objective or a list on it by that name, and what is
marked done there is CLIVE's own record.

What is held here: a name is one screen however it is typed, and it is bound to the device the
owner read its code from; a spoken name finds it or is answered plainly; what a screen shows
moves only forward; a late tap never marks the wrong thing; pages are told in order and not
hurried; a deletion is never said done before it is durable; every route and every tool is the
owner's alone; and the page is served without the data it draws, and lets go of it when it must."""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.displays import store as store_module
from app.displays import views
from app.displays.store import (
    ACK_GAP_S,
    MAX_DONE,
    MAX_SCREENS,
    ONLINE_S,
    PAIR_CODE_S,
    PAIR_TRIES,
    SHOWING_KEEP_S,
    DisplayError,
    DisplayStore,
    NameTaken,
    NotDurable,
    NotPaired,
    NotSaved,
    NotSeen,
    NotThisScreen,
    TooMany,
)
from app.tools import authority, gate
from app.tools.gate import Tier
from app.tools.registry import ToolError

OWNER_LOGIN = "owner@example.com"


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Tick(Clock):
    """A monotonic clock a test moves by hand: the store's pace for page acknowledgements."""

    def __init__(self) -> None:
        super().__init__(time.monotonic())


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives" / "displays.json", mono=Tick())


def later(store, seconds: float = ACK_GAP_S):
    """Time passes on the store's own pace clock (a screen looks at a page before the next)."""
    if not isinstance(store.mono, Clock):
        store.mono = Tick()
    store.mono.now += seconds + 0.01


def pair(store, name):
    """Name a screen and approve it with the code it was given, as the owner does by reading the
    code off the device and saying it."""
    made = store.register(name)
    assert made["pending"] is True
    assert store.approve(name, made["code"])["approved"] is True
    return made


def ack_all(store, screen_id, key, *, version=None, upto=None):
    """The screen puts up every page of what it shows (or the first `upto` items), a page at a
    time, in order and a second apart, as web/display.js does; then it is looked at a moment."""
    now = store.poll(screen_id, key)
    version = now["version"] if version is None else version
    count = store_module._shown_count(now["showing"] or {}) or 0
    end = count if upto is None else upto
    for start in range(0, end, store_module.MAX_ACK):
        later(store)
        store.acknowledge(screen_id, version, screen_key=key, start=start, end=min(end, start + store_module.MAX_ACK))
    later(store)


def owner():
    return authority.for_owner(OWNER_LOGIN)


def run(coro, *, held="owner"):
    """A tool called directly, under the authority it is given (the owner's by default)."""
    with authority.acting_as(owner() if held == "owner" else held):
        return asyncio.run(coro)


@contextmanager
def owner_saying(words: str):
    """The owner's own words in the request being answered (the session's `heard`)."""
    from app.session.models import Session
    from app.tools.context import CURRENT_SESSION

    session = Session(session_id="screens-heard")
    session.heard = words
    token = CURRENT_SESSION.set(session)
    try:
        yield session
    finally:
        CURRENT_SESSION.reset(token)


# --------------------------------------------------------------------------- the record


def test_a_name_is_one_screen_however_it_is_typed_and_never_passes_to_another_device(tmp_path):
    """Rounds 6 and 7, B-02: knowing a screen's name is not being that screen, and neither is
    waiting until it goes quiet or the service restarts. Naming hands the device a key; the name
    is refused to anyone else, whenever they ask; the device holding the key may name it again (and
    gets a new key); and only the owner removing the old screen frees the name — for a new screen
    with nothing on it."""
    clock = Clock()
    path = tmp_path / "displays.json"
    s = DisplayStore(path, clock=clock)
    first = pair(s, "Office screen")
    key = first["screen_key"]
    assert len(key) >= 24 and "secret" not in first and "pairing" not in first
    s.show(first["id"], views.order_view(ORDER))
    assert s.poll(first["id"], key)["name"] == "Office screen"
    for wrong in ("", "guess", first["id"]):
        with pytest.raises(NotThisScreen):
            s.poll(first["id"], wrong)
    assert key not in path.read_text(), "only the key's hash is kept"
    assert f'"{first["code"]}"' not in path.read_text(), "nor is the code kept"
    # Quiet for a long time, and then a restart (the memory of when it was last seen is gone):
    # the name is still not anyone's for the asking.
    clock.now += ONLINE_S * 100
    for store in (s, DisplayStore(path, clock=clock)):
        with pytest.raises(NameTaken, match="already a screen called Office screen"):
            store.register("  office   SCREEN! ")
        with pytest.raises(NameTaken):
            store.register("Office screen", screen_key="guess")
    # The device that holds the key may name it again, and is given a new one.
    again = s.register("Office screen", screen_key=key)
    assert again["id"] == first["id"] and again["screen_key"] != key and again["pending"] is False
    with pytest.raises(NotThisScreen):
        s.poll(first["id"], key)
    assert s.poll(first["id"], again["screen_key"])["showing"]["kind"] == "order", "the same screen, still showing"
    # The owner removes it: its key and what it showed go with it, and the name is free again —
    # for a NEW screen, with nothing on it.
    assert s.forget(first["id"]) is True
    fresh = s.register("Office screen")
    assert fresh["id"] != first["id"] and s.poll(fresh["id"], fresh["screen_key"])["showing"] is None
    assert "Sam Carter" not in path.read_text()
    assert [x["name"] for x in s.screens()] == ["Office screen"]
    with pytest.raises(DisplayError, match="Give the screen a name"):
        s.register("  !!  ")


def test_a_spoken_name_finds_its_screen_or_is_answered_plainly(s):
    with pytest.raises(DisplayError, match="No screens yet"):
        s.find("office screen")
    s.register("Office screen")
    s.register("Bedroom TV")
    s.register("Packing screen")
    assert s.find("office screen")["name"] == "Office screen"
    assert s.find("bedroom")["name"] == "Bedroom TV"
    with pytest.raises(DisplayError, match="More than one screen fits 'screen'"):
        s.find("screen")
    with pytest.raises(DisplayError, match="There is no screen called 'kitchen'. The screens are: Bedroom TV, Office screen, Packing screen."):
        s.find("kitchen")


def test_what_a_screen_shows_moves_forward_and_a_late_tap_marks_nothing(s):
    screen = pair(s, "Office screen")
    key = screen["screen_key"]
    assert s.poll(screen["id"], key)["version"] == 0
    s.show(screen["id"], views.list_view("Today", ["One", "Two"]))
    shown = s.poll(screen["id"], key)
    assert shown["version"] == 1 and shown["showing"]["title"] == "Today" and shown["showing"]["at"]
    # A tap on what the screen drew before the change is refused, and nothing is recorded.
    with pytest.raises(DisplayError, match="changed before that tap"):
        s.mark_done(screen["id"], 0, screen_key=key, confirmed=True, by=OWNER_LOGIN)
    # Nor from a device without the key, nor with only part of the list put up.
    with pytest.raises(NotThisScreen):
        s.mark_done(screen["id"], 1, screen_key="guess", confirmed=True)
    ack_all(s, screen["id"], key, upto=1)
    with pytest.raises(NotSeen, match="Not every line of the list has been on the screen"):
        s.mark_done(screen["id"], 1, screen_key=key, confirmed=True)
    assert s.done() == []
    ack_all(s, screen["id"], key)
    s.mark_done(screen["id"], 1, screen_key=key, confirmed=True, by=OWNER_LOGIN)
    after = s.poll(screen["id"], key)
    assert after["version"] == 2 and after["showing"]["done_at"]
    assert after["last_done"]["title"] == "List", "a list's own title is the owner's words and is not kept"
    # A second tap on the same thing is the same record, not another.
    s.mark_done(screen["id"], 2, screen_key=key, confirmed=True)
    assert len(s.done()) == 1 and s.done()[0]["by"] == OWNER_LOGIN
    # Clearing empties it.
    s.show(screen["id"], None)
    assert s.poll(screen["id"], key)["showing"] is None


def test_the_done_record_is_per_screen_and_bounded(s):
    a = pair(s, "Office screen")
    b = pair(s, "Packing screen")
    s.show(a["id"], {"kind": "order", "ref": "gid://shopify/Order/1", "title": "Order 1001"})
    s.mark_done(a["id"], 1, screen_key=a["screen_key"], confirmed=True)
    assert s.poll(b["id"], b["screen_key"])["last_done"] is None, "done on one screen is not done on another"
    assert s.done(ref="gid://shopify/Order/1")[0]["screen"] == "Office screen"
    for i in range(MAX_DONE + 5):
        s.show(b["id"], {"kind": "list", "ref": "", "title": f"List {i}"})
        s.mark_done(b["id"], s.poll(b["id"], b["screen_key"])["version"], screen_key=b["screen_key"], confirmed=True)
    assert len(s._data["done"]) == MAX_DONE


def test_the_record_is_private_on_disk_and_survives_a_restart(tmp_path):
    path = tmp_path / "objectives" / "displays.json"
    s = DisplayStore(path)
    screen = pair(s, "Office screen")
    s.show(screen["id"], views.list_view("Today", ["One"]))
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    again = DisplayStore(path)
    assert again.poll(screen["id"], screen["screen_key"])["showing"]["title"] == "Today"
    path.write_text("{not json", encoding="utf-8")
    assert DisplayStore(path).screens() == [], "an unreadable record starts afresh rather than failing"


def test_only_a_real_screen_id_is_looked_up(s):
    s.register("Office screen")
    assert s.get("../../etc/passwd") is None and s.get("scr_zzzzzzzzzzzz") is None
    assert s.poll("scr_000000000000", "any") is None


# --------------------------------------------------------------------------- the views


ORDER = {
    "order_id": "gid://shopify/Order/1047",
    "order_number": "#1047",
    "placed_at": "2026-09-27T11:20:00Z",
    "payment": "PAID",
    "fulfillment": "UNFULFILLED",
    "shipping_method": "Tracked 48",
    "customer_name": "Sam Carter",
    "note": "It's a gift, please leave the receipt out.",
    "tags": ["Gift"],
    "shipping_address": {"name": "Sam Carter", "company": None, "lines": ["14 Sample Road"], "city": "London",
                         "province": None, "zip": "E8 1AA", "country": "United Kingdom"},
    "items": [
        {"title": "Canvas Tote", "variant": "Natural", "sku": "CV-TOTE", "quantity": 1, "current_quantity": 1,
         "unfulfilled_quantity": 0, "image_url": "https://cdn.example.com/tote.jpg"},
        {"title": "Heavyweight Tee", "product_title": "Heavyweight Tee", "variant": "Black / L", "sku": "HW-TEE",
         "quantity": 2, "current_quantity": 2, "unfulfilled_quantity": 2, "image_url": "http://insecure.example.com/x.jpg"},
    ],
}


def test_the_slip_puts_what_is_still_to_send_first_and_carries_only_safe_images():
    v = views.order_view(ORDER)
    o = v["order"]
    assert v["kind"] == "order" and v["title"] == "Order #1047" and v["ref"] == "gid://shopify/Order/1047"
    assert [i["title"] for i in o["items"]] == ["Heavyweight Tee", "Canvas Tote"]
    assert o["items"][0]["to_send"] == 2 and o["items"][1]["to_send"] == 0
    assert o["items"][0]["image"] is None, "only an https image is drawn"
    assert o["items"][1]["image"] == "https://cdn.example.com/tote.jpg"
    assert o["address"] == ["14 Sample Road", "London", "E8 1AA", "United Kingdom"]
    assert o["customer"] == "Sam Carter" and o["shipping_method"] == "Tracked 48" and o["payment"] == "PAID"


def test_an_objective_shows_the_work_not_yet_started_in_order():
    summary = {"id": "obj_1", "title": "Get the drop live", "deadline": "2026-10-03", "days_left": 6,
               "doing": "Writing product copy", "next": [], "needs_you": ["Approve the hero image"], "blocked_by": []}
    items = [
        {"text": "Writing product copy", "state": "started"},
        {"text": "Resize the lookbook", "state": "proposed"},
        {"text": "Schedule the email", "state": "authorised"},
        {"text": "Brief the team", "state": "completed"},
    ]
    v = views.objective_view(summary, items)
    g = v["objective"]
    assert g["next"] == ["Resize the lookbook", "Schedule the email"] and g["days_left"] == 6
    assert [i["text"] for i in g["items"]] == ["Writing product copy", "Resize the lookbook", "Schedule the email"]


def test_a_list_is_bounded_and_blank_lines_are_dropped():
    v = views.list_view("  Emily's list  ", ["One", "", "   ", "x" * 500] + [f"L{i}" for i in range(60)])
    assert v["title"] == "Emily's list" and v["list"]["lines"][0] == "One"
    assert len(v["list"]["lines"]) == views.MAX_LINES and len(v["list"]["lines"][1]) == views.MAX_LINE


# --------------------------------------------------------------------------- the tools


class FakeHydrator:
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def order(self, order_id: str, *, budget_s: float = 0.0, **_):
        self.asked.append(order_id)
        return dict(ORDER, order_id=order_id)


def test_screen_show_puts_an_order_slip_on_the_named_screen(s, monkeypatch):
    from app.tools import display_tools, shopify_tools

    fake = FakeHydrator()
    monkeypatch.setattr(shopify_tools, "_hydrator", fake)
    clock = Clock()
    s.clock = clock
    pair(s, "Office screen")
    clock.now += 120   # it has not asked for anything since: it is off
    out = run(display_tools.screen_show(screen="office screen", order_id="gid://shopify/Order/1047"))
    assert out["screen"] == "Office screen" and out["showing"] == "Order #1047"
    assert fake.asked == ["gid://shopify/Order/1047"]
    assert out["on"] is False and "next on" in out["note"]
    showing = s._data["screens"][s.find("office")["id"]]["showing"]
    assert showing["kind"] == "order" and showing["order"]["customer"] == "Sam Carter" and showing["by"] == "clive"


def test_screen_show_takes_one_thing_and_names_the_screens_it_knows(s):
    from app.tools import display_tools

    pair(s, "Office screen")
    with pytest.raises(ToolError, match="Say one thing to show"):
        run(display_tools.screen_show(screen="office screen"))
    with pytest.raises(ToolError, match="Say one thing to show"):
        run(display_tools.screen_show(screen="office screen", title="T", lines=["a"], clear=True))
    with pytest.raises(ToolError, match="Say its full name: Office screen"):
        run(display_tools.screen_show(screen="kitchen", title="T", lines=["a"]))
    out = run(display_tools.screen_show(screen="office screen", title="Emily's list", lines=["Steam the jackets"]))
    assert out["showing"] == "Emily's list"
    cleared = run(display_tools.screen_show(screen="office screen", clear=True))
    assert cleared["showing"] == "nothing"


def test_screen_show_puts_an_objective_up(s, tmp_path):
    from app.objectives import store as objectives_store
    from app.tools import display_tools

    objectives = objectives_store.install(tmp_path / "objectives-store")
    obj = objectives.create(title="Get the drop live", request="Get the SS26 drop live by Friday")
    objectives.propose(obj.id, "Resize the lookbook images", needs_owner=False)
    pair(s, "Office screen")
    out = run(display_tools.screen_show(screen="office screen", objective_id=obj.id))
    assert out["showing"] == "Get the drop live"
    showing = s._data["screens"][s.find("office")["id"]]["showing"]
    assert showing["objective"]["next"] == ["Resize the lookbook images"]
    with pytest.raises(ToolError, match="There is no objective"):
        run(display_tools.screen_show(screen="office screen", objective_id="obj_00000000"))


def test_screen_list_says_what_is_up_and_what_was_packed(s):
    from app.tools import display_tools

    empty = run(display_tools.screen_list())
    assert empty["screens"] == [] and "/display" in empty["note"]
    screen = pair(s, "Packing screen")
    s.show(screen["id"], {"kind": "order", "ref": "gid://shopify/Order/1047", "title": "Order #1047"})
    s.poll(screen["id"], screen["screen_key"])   # the screen asked: it is on
    s.mark_done(screen["id"], 1, screen_key=screen["screen_key"], confirmed=True, by=OWNER_LOGIN)
    out = run(display_tools.screen_list(order_id="gid://shopify/Order/1047"))
    assert out["screens"][0]["online"] is True and out["screens"][0]["showing"] == "Order #1047"
    assert out["done"][0]["ref"] == "gid://shopify/Order/1047" and out["done"][0]["screen"] == "Packing screen"
    assert run(display_tools.screen_list(order_id="gid://shopify/Order/9"))["done"] == []


def test_the_gate_lets_a_slip_through_only_for_an_order_this_conversation_looked_up():
    from app.tools import display_tools  # noqa: F401  registers the tools

    oid = "gid://shopify/Order/1047"
    refused = gate.classify("screen_show", {"screen": "office screen", "order_id": oid}, issued_ids=[])
    assert refused.tier is Tier.RED and "not an id this conversation has looked up" in refused.reason
    assert gate.classify("screen_show", {"screen": "office screen", "order_id": oid}, issued_ids=[oid]).tier is Tier.AMBER
    # Without an order the id rule does not apply: a list or an objective needs no lookup.
    assert gate.classify("screen_show", {"screen": "office screen", "title": "T", "lines": ["a"]}, issued_ids=[]).tier is Tier.AMBER
    assert gate.classify("screen_list", {}, issued_ids=[]).tier is Tier.GREEN
    # And an objective (round 6, B-05): issued, and of the objective kind, or not at all.
    obj = "obj_0123abcd"
    assert gate.classify("screen_show", {"screen": "office screen", "objective_id": obj}, issued_ids=[]).tier is Tier.RED
    assert gate.classify("screen_show", {"screen": "office screen", "objective_id": obj}, issued_ids=[obj]).tier is Tier.AMBER
    assert gate.classify("screen_show", {"screen": "office screen", "objective_id": oid}, issued_ids=[oid]).tier is Tier.RED
    # Round 8, B-02: approving a screen is on the allow-list and runs (it is not a store write).
    approving = gate.classify("screen_pair", {"screen": "office screen", "code": "123 456"}, issued_ids=[])
    assert approving.tier is Tier.GREEN and approving.executes


# --------------------------------------------------------------------------- the routes


def app_with(s, *, allowed=(OWNER_LOGIN,), local_owner=False) -> TestClient:
    from app.routes import displays

    app = FastAPI()
    app.include_router(displays.router)
    settings = SimpleNamespace(writes_local_owner=local_owner, tailscale_verify=False, tailscale_cli="")
    app.state.runtime = SimpleNamespace(allowed_logins=allowed, settings=settings)
    return TestClient(app)


OWNER = {"Tailscale-User-Login": OWNER_LOGIN, "X-Forwarded-For": "100.64.0.9"}


def test_every_screen_route_is_the_owners_alone(s):
    client = app_with(s)
    screen = s.register("Office screen")
    for method, path, body in (
        ("get", "/displays", None),
        ("post", "/displays/register", {"name": "Kitchen"}),
        ("get", f"/displays/{screen['id']}", None),
        ("post", f"/displays/{screen['id']}/done", {"version": 0, "confirm": True}),
        ("post", f"/displays/{screen['id']}/seen", {"version": 0, "start": 0, "end": 1}),
        ("post", "/displays/forget", {"name": "Office screen"}),
    ):
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, **kwargs).status_code == 403, f"{path} from the server itself"
        stranger = {**OWNER, "Tailscale-User-Login": "someone@example.com"}
        assert getattr(client, method)(path, headers=stranger, **kwargs).status_code == 403, f"{path} from a stranger"
    assert client.get("/displays", headers=OWNER).status_code == 200
    assert app_with(s, local_owner=True).get("/displays").status_code == 200, "the owner said the server is him"


def test_a_screen_names_itself_asks_and_marks_done(s):
    client = app_with(s)
    answer = client.post("/displays/register", json={"name": "Packing screen"}, headers=OWNER)
    made = answer.json()
    assert made["name"] == "Packing screen" and made["id"].startswith("scr_") and made["key"]
    assert answer.headers["cache-control"] == "no-store"
    mine = {**OWNER, "X-Screen-Key": made["key"]}
    # Round 8, B-02: named, it waits for approval with the code it was given, and is shown nothing.
    assert made["pending"] is True and re.fullmatch(r"\d{6}", made["code"]) and made["code_expires_in"] == PAIR_CODE_S
    waiting = client.get(f"/displays/{made['id']}?v=0", headers=mine)
    assert waiting.status_code == 200 and waiting.json()["pending"] is True and waiting.json()["showing"] is None
    assert s.approve("Packing screen", made["code"])["approved"] is True
    first = client.get(f"/displays/{made['id']}?v=-1", headers=mine)
    assert first.status_code == 200 and first.json()["version"] == 0 and first.json()["showing"] is None
    assert first.json()["pending"] is False
    assert client.get(f"/displays/{made['id']}?v=0", headers=mine).status_code == 204, "nothing new, nothing sent"
    # The owner's other device, knowing the id and the name but not the key, is not the screen.
    for headers in (OWNER, {**OWNER, "X-Screen-Key": "guess"}):
        refused = client.get(f"/displays/{made['id']}?v=-1", headers=headers)
        assert refused.status_code == 403 and refused.json()["code"] == "not_this_screen"
    taken = client.post("/displays/register", json={"name": "packing SCREEN"}, headers=OWNER)
    assert taken.status_code == 409 and taken.json()["code"] == "name_taken"
    s.show(made["id"], views.list_view("Today", ["One"]))
    now = client.get(f"/displays/{made['id']}?v=0", headers=mine).json()
    assert now["version"] == 1 and now["showing"]["title"] == "Today"
    stale = client.post(f"/displays/{made['id']}/done", json={"version": 0, "confirm": True}, headers=mine)
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    keyless = client.post(f"/displays/{made['id']}/done", json={"version": 1, "confirm": True}, headers=OWNER)
    assert keyless.status_code == 403 and keyless.json()["code"] == "not_this_screen"
    # Round 7, B-04: a "done" that claims everything was seen, with nothing acknowledged, is refused.
    claimed = client.post(f"/displays/{made['id']}/done", json={"version": 1, "items_seen": 1, "confirm": True}, headers=mine)
    assert claimed.status_code == 409 and claimed.json()["code"] == "not_seen"
    assert client.post(f"/displays/{made['id']}/seen", json={"version": 1, "start": 0, "end": 1}, headers=OWNER).status_code == 403
    assert client.post(f"/displays/{made['id']}/seen", json={"version": 1, "start": 0, "end": 1}, headers=mine).json() == {"seen": 1}
    later(s)
    done = client.post(f"/displays/{made['id']}/done", json={"version": 1, "confirm": True}, headers=mine).json()
    assert done["version"] == 2 and done["showing"]["done_at"] and done["last_done"]["title"] == "List"
    assert s.done()[0]["by"] == OWNER_LOGIN
    # The owner frees the name, explicitly; a device named it afresh gets a new, empty screen.
    assert client.post("/displays/forget", json={"name": "Packing Screen"}, headers=OWNER).json() == {"forgotten": "Packing screen"}
    anew = client.post("/displays/register", json={"name": "Packing screen"}, headers=OWNER).json()
    assert anew["id"] != made["id"] and anew["pending"] is True
    assert client.get(f"/displays/{made['id']}?v=-1", headers=mine).status_code == 404
    assert client.post("/displays/forget", json={"name": "Kitchen"}, headers=OWNER).status_code == 404
    assert client.get("/displays/scr_000000000000", headers=mine).status_code == 404
    assert client.post("/displays/register", json={"name": "!!!"}, headers=OWNER).status_code == 409


def test_the_page_is_served_fresh_with_the_build_and_no_data(tmp_path, monkeypatch):
    monkeypatch.setenv("CROOKS_OBJECTIVES_DIR", str(tmp_path / "objectives"))
    from app.main import app

    with TestClient(app) as client:
        page = client.get("/display")
        assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
        assert "__BUILD__" not in page.text and 'name="crooks-build"' in page.text
        assert '<script src="/static/dots.js"></script>' in page.text and '<script src="/static/display.js"></script>' in page.text
        assert "Order" not in page.text, "the page holds no order; it asks for what to show"
        assert client.get("/static/display.js").status_code == 200
        assert client.get("/static/dots.js").status_code == 200


def test_the_pages_a_browser_may_keep_are_the_same_for_every_login(tmp_path, monkeypatch):
    """Round 6, B-07: the worker keeps the app's page and files and nothing else, so what it
    keeps must not depend on who asked. The page, the screen page, the worker and the manifest
    are byte for byte the same for the owner's device and the server itself, and a login not on
    the list is refused them outright; what differs by login is only ever asked for afresh, and
    a refusal is never kept (tests/web/sw.test.js)."""
    monkeypatch.setenv("CROOKS_OBJECTIVES_DIR", str(tmp_path / "objectives"))
    from app.main import app

    stranger = {"Tailscale-User-Login": "someone@example.com", "X-Forwarded-For": "100.64.0.3"}
    with TestClient(app) as client:
        runtime = app.state.runtime
        # Both devices taken as really arriving through `tailscale serve` (the proof of that is
        # tests/test_proxy_identity.py); the owner's login on the list, the stranger's not.
        runtime.settings = runtime.settings.model_copy(update={"tailscale_verify": False, "allowed_logins": OWNER_LOGIN})
        app.state.allowed_logins = runtime.allowed_logins
        for path in ("/", "/display", "/sw.js", "/manifest.webmanifest", "/static/app.js"):
            answers = {client.get(path, headers=h).content for h in ({}, OWNER)}
            assert len(answers) == 1, f"{path} differs by who asked"
            # A login not on the list is refused even the page; the worker never keeps a refusal.
            assert client.get(path, headers=stranger).status_code == 403
        for path in ("/displays", "/objectives"):
            assert client.get(path, headers=stranger).status_code == 403


# --------------------------------------------------------------------------- the page


WEB = Path(__file__).resolve().parents[1] / "web"


def test_the_screen_page_builds_every_word_as_text_and_talks_only_to_its_own_routes():
    source = (WEB / "display.js").read_text(encoding="utf-8")
    assert "textContent" in source
    for forbidden in (".innerHTML", "insertAdjacentHTML(", "document.write("):
        assert forbidden not in source
    # The only calls: ask what to show, say it was done, and name the screen.
    assert "fetch('/displays/' + encodeURIComponent(S.screen.id) + '?v=' + S.version" in source
    assert "fetch('/displays/' + encodeURIComponent(S.screen.id) + '/done'" in source
    assert "fetch('/displays/register'" in source
    # A late tap is answered as one, and an image is only ever an https one.
    assert "response.status === 409" in source and "/^https:\\/\\//.test(it.image)" in source


def test_the_start_up_waits_for_clive_and_never_holds_the_app_hostage():
    source = (WEB / "startup.js").read_text(encoding="utf-8")
    css = (WEB / "startup.css").read_text(encoding="utf-8")
    # The whole of it on the first open of a day and after an update; the name alone otherwise.
    assert "seen.day !== today || seen.build !== BUILD" in source
    # It hands over only when the system layer says CLIVE answered, and steps aside if it cannot.
    assert "phase() === 'online'" in source and "phase() === 'offline' || phase() === 'refused'" in source
    assert "setTimeout(bail, 20000)" in source
    # If the script never runs, the page gets out of the way by itself.
    assert "animation:startup-giveway 0s linear 12s forwards" in css and ".startup.is-live{animation:none}" in css
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert index.index('<script src="/static/startup.js"></script>') < index.index('<script src="/static/app.js"></script>')
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    for path in ("/static/dots.js", "/static/startup.js", "/static/startup.css"):
        assert f"'{path}'" in sw, f"{path} is part of the installed app"


def test_the_screen_page_keeps_nothing_but_its_name():
    source = (WEB / "display.js").read_text(encoding="utf-8")
    stored = set(re.findall(r"localStorage\.setItem\((\w+)", source))
    assert stored == {"KEY", "BOOT_KEY"}
    assert "JSON.stringify(s)" in source and "{ day: new Date().toDateString(), build: BUILD }" in source
    # Round 8, B-02: the approval code is shown, never written down on the device.
    assert "S.screen = { id: data.id, name: data.name || name, key: data.key };" in source
    assert "pairCode" not in source[source.index("function saveScreen"):source.index("function forgetScreen")]


# --------------------------------------------------------------------------- round 6


def test_a_packed_slip_keeps_nothing_about_the_customer(tmp_path):
    """Round 6, B-03: done set done_at and kept the whole slip, name, address, phone and note,
    for good. Done cuts the slip down to what the done record needs, on disk as in memory."""
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    screen = pair(s, "Packing screen")
    key = screen["screen_key"]
    s.show(screen["id"], views.order_view(ORDER))
    assert "Sam Carter" in path.read_text(), "while it is up, the slip is the slip"
    ack_all(s, screen["id"], key)
    s.mark_done(screen["id"], 1, screen_key=key, confirmed=True)
    kept = path.read_text()
    for gone in ("Sam Carter", "07700", "E8 1AA", "Sample Road", "gift", "HW-TEE"):
        assert gone not in kept, gone
    assert not s.journal_path.exists(), "durable, so nothing is owed"
    showing = s.poll(screen["id"], key)["showing"]
    assert set(showing) == {"kind", "ref", "title", "at", "by", "done_at"}
    assert showing["title"] == "Order #1047" and showing["ref"] == ORDER["order_id"]


def test_an_order_is_marked_packed_only_once_every_item_was_acknowledged_on_the_screen(s):
    """Round 6, B-04: the screen showed 6 or 12 items and "+N more", with Mark packed live. Round
    7: the page then asserted a count the server took on trust. Now the server keeps which items
    the screen acknowledged putting up, a page at a time, for the version showing now."""
    screen = pair(s, "Packing screen")
    key = screen["screen_key"]
    many = dict(ORDER, items=[dict(ORDER["items"][1], title=f"Tee {i}", sku=f"SKU-{i}") for i in range(20)])
    slip = views.order_view(many)
    s.show(screen["id"], slip)
    n = len(slip["order"]["items"])
    assert n > store_module.MAX_ACK
    # A direct "done" that has acknowledged nothing, or part: refused.
    with pytest.raises(NotSeen, match="Not every item on the order has been on the screen"):
        s.mark_done(screen["id"], 1, screen_key=key, confirmed=True)
    ack_all(s, screen["id"], key, upto=10)
    with pytest.raises(NotSeen):
        s.mark_done(screen["id"], 1, screen_key=key, confirmed=True)
    # Not the whole order in one word: an acknowledgement is a page at most, and inside the slip.
    for start, end in ((0, n), (0, store_module.MAX_ACK + 1), (15, n + 1), (5, 5)):
        with pytest.raises(DisplayError, match="A page is at most"):
            s.acknowledge(screen["id"], 1, screen_key=key, start=start, end=end)
    with pytest.raises(NotThisScreen):
        s.acknowledge(screen["id"], 1, screen_key="guess", start=10, end=20)
    with pytest.raises(DisplayError, match="changed before that"):
        s.acknowledge(screen["id"], 0, screen_key=key, start=10, end=20)
    assert s.done() == []
    s.acknowledge(screen["id"], 1, screen_key=key, start=10, end=20)
    later(s)
    s.mark_done(screen["id"], 1, screen_key=key, confirmed=True)
    assert len(s.done()) == 1
    # Acknowledgements belong to a version: a new slip starts from none.
    s.show(screen["id"], slip)
    with pytest.raises(NotSeen):
        s.mark_done(screen["id"], 3, screen_key=key, confirmed=True)
    src = (Path(__file__).resolve().parent.parent / "web" / "display.js").read_text()
    assert "+ ' more on the order" not in src and "Ask CLIVE for the rest" not in src
    assert "items_seen" not in src and "'/seen'" in src and "packedLocked()" in src
    assert "'Next items'" in src and "'Next page'" in src and "X-Screen-Key" in src


def test_after_a_restart_every_page_must_be_shown_again_before_done(tmp_path):
    """Acknowledgements are held in memory: a restart between them and the tap means the pages go
    up again first."""
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    screen = pair(s, "Packing screen")
    key = screen["screen_key"]
    s.show(screen["id"], views.list_view("Today", ["One", "Two"]))
    ack_all(s, screen["id"], key)
    restarted = DisplayStore(path, mono=Tick())
    with pytest.raises(NotSeen):
        restarted.mark_done(screen["id"], 1, screen_key=key, confirmed=True)
    ack_all(restarted, screen["id"], key)
    restarted.mark_done(screen["id"], 1, screen_key=key, confirmed=True)


def test_whatever_is_left_up_comes_down_by_itself(tmp_path):
    clock = Clock()
    s = DisplayStore(tmp_path / "displays.json", clock=clock)
    screen = pair(s, "Office screen")
    import app.displays.store as st

    real_now = st._now_iso
    st._now_iso = lambda: __import__("datetime").datetime.fromtimestamp(clock.now, __import__("datetime").UTC).isoformat(timespec="seconds")
    try:
        s.show(screen["id"], views.order_view(ORDER))
        clock.now += SHOWING_KEEP_S - 60
        assert s.poll(screen["id"], screen["screen_key"])["showing"]["title"] == "Order #1047"
        clock.now += 120
        gone = s.poll(screen["id"], screen["screen_key"])
        assert gone["showing"] is None and gone["version"] == 2
        assert "Sam Carter" not in (tmp_path / "displays.json").read_text()
    finally:
        st._now_iso = real_now


def test_the_start_up_is_taken_away_whatever_fails():
    """Round 6, B-06: is-live (which switches off the stylesheet's own give-way) was added before
    the dots engine was built, and the escape timer only after it, so a failure between left an
    opaque overlay over the app. The way out now comes first and every step runs inside it."""
    src = (Path(__file__).resolve().parent.parent / "web" / "startup.js").read_text()
    escape = src.index("setTimeout(bail, 20000)")
    live = src.index("root.classList.add('is-live')")
    engine = src.index("window.CliveDots.create(")
    assert escape < engine < live, "the escape before the engine, is-live only after it"
    assert src.count("catch (e) { bail(); }") >= 1 and "} catch (e) {\n    bail();\n  }\n})();" in src
    css = (Path(__file__).resolve().parent.parent / "web" / "startup.css").read_text()
    assert "animation:startup-giveway" in css and ".startup.is-live{animation:none}" in css


def test_a_slip_cut_at_the_screens_limit_is_never_marked_packed(s):
    """Round 6, B-04: order_view keeps views.MAX_ITEMS items. Past that the rest of the order was
    never on any screen, so the slip says it is partial and done is refused whatever is claimed."""
    screen = pair(s, "Packing screen")
    key = screen["screen_key"]
    many = dict(ORDER, items=[dict(ORDER["items"][1], title=f"Tee {i}", sku=f"SKU-{i}") for i in range(views.MAX_ITEMS + 15)])
    slip = views.order_view(many)
    o = slip["order"]
    assert o["partial"] is True and o["total_items"] == views.MAX_ITEMS + 15 and len(o["items"]) == views.MAX_ITEMS
    assert "partial" not in views.order_view(ORDER)["order"]
    s.show(screen["id"], slip)
    ack_all(s, screen["id"], key)       # every item it has, acknowledged: still not the whole order
    with pytest.raises(DisplayError, match="more items than a screen shows"):
        s.mark_done(screen["id"], 1, screen_key=key, confirmed=True)
    assert s.done() == [] and s.poll(screen["id"], key)["showing"].get("done_at") is None
    src = (WEB / "display.js").read_text(encoding="utf-8")
    assert "const partial = !!o.partial && !packed;" in src and "noteFoot(" in src


def test_every_field_of_a_view_is_bounded_and_the_record_stays_small(tmp_path):
    """Round 6, B-03: address lines, ids, times, image addresses and the whole view were
    unbounded. A hostile order, objective and list are cut to size before they are kept, a view
    past MAX_VIEW_BYTES is refused, and a full record — every screen at its largest, the done
    record full — stays under MAX_FILE_BYTES."""
    huge = "x" * 1_000_000
    url = "https://" + huge             # one string, shared: 5,000 copies would be 5 GB
    hostile = {
        "order_id": "gid://shopify/Order/" + "9" * 5000, "order_number": huge, "placed_at": huge,
        "customer_name": huge, "note": huge, "tags": [huge] * 10_000, "payment": huge, "fulfillment": huge,
        "shipping_method": huge,
        "shipping_address": {"name": huge, "company": huge, "phone": huge, "lines": [huge] * 10_000,
                             "city": huge, "province": huge, "zip": huge, "country": huge},
        "items": [{"title": huge, "variant": huge, "sku": huge, "quantity": 10**30, "unfulfilled_quantity": -5,
                   "image_url": url} for _ in range(5000)],
    }
    order = views.order_view(hostile)
    obj = views.objective_view({"id": huge, "title": huge, "deadline": huge, "days_left": -(10**20), "doing": huge,
                                "next": [huge] * 10_000, "needs_you": [huge] * 10_000, "blocked_by": [huge] * 10_000},
                               [{"text": huge, "state": "proposed"}] * 10_000)
    lst = views.list_view(huge, [huge] * 10_000)
    for view in (order, obj, lst):
        assert len(json.dumps(view).encode()) < views.MAX_VIEW_BYTES
    o = order["order"]
    assert len(o["address"]) <= views.MAX_ADDRESS_LINES + 4 and len(o["tags"]) <= 10 and len(order["ref"]) <= views.MAX_ID
    assert all(i["image"] is None and i["quantity"] <= 100_000 and i["to_send"] == 0 for i in o["items"])
    assert obj["objective"]["days_left"] == -100_000 and len(lst["list"]["lines"]) == views.MAX_LINES

    s = DisplayStore(tmp_path / "displays.json")
    with pytest.raises(DisplayError, match="more than one screen can show"):
        s.show(pair(s, "Office screen")["id"], {"kind": "list", "title": "T", "list": {"lines": ["y" * 200_000]}})
    for i in range(MAX_SCREENS):
        made = pair(s, f"Screen {i}") if i else s.find("office screen")
        s.show(made["id"], order)
    s._data["done"] = [{"at": "2999-01-01T00:00:00+00:00", "screen": "S" * 40, "screen_id": "scr_000000000000",
                        "kind": "order", "ref": "r" * 200, "title": "t" * 120, "by": "b" * 80}] * MAX_DONE
    s._write()
    assert (tmp_path / "displays.json").stat().st_size < store_module.MAX_FILE_BYTES


def test_housekeeping_takes_a_slip_down_with_no_screen_asking_and_at_start_up(tmp_path, monkeypatch):
    """Round 6, B-03: expiry ran only when a screen asked or CLIVE listed the screens, so a slip
    on a screen that was switched off stayed on disk for good. The backend's housekeeping pass
    takes it down on its own, the record is swept when it is first read after a start, and done
    rows age out too."""
    import datetime as dt

    from app.main import housekeep_once

    clock = Clock()
    stamp = {"now": clock.now}
    monkeypatch.setattr(store_module, "_now_iso", lambda: dt.datetime.fromtimestamp(stamp["now"], dt.UTC).isoformat(timespec="seconds"))
    path = tmp_path / "objectives" / "displays.json"
    s = store_module.install(path)
    s.clock = clock
    screen = pair(s, "Packing screen")
    s.show(screen["id"], views.order_view(ORDER))
    assert "Sam Carter" in path.read_text()

    clock.now += SHOWING_KEEP_S + 60             # nobody asks: the screen is off
    assert housekeep_once(object()) == ""        # the timer's pass, with no test mode at all
    assert "Sam Carter" not in path.read_text() and s._data["screens"][screen["id"]]["showing"] is None

    # A slip and an old done row written down, then the service is stopped for a day.
    stamp["now"] = clock.now
    s.show(screen["id"], views.order_view(ORDER))
    s._data["done"] = [{"at": dt.datetime.fromtimestamp(clock.now - store_module.DONE_KEEP_S - 60, dt.UTC).isoformat(timespec="seconds"),
                        "screen": "Packing screen", "ref": "gid://shopify/Order/1", "title": "Order #1", "kind": "order"},
                       {"at": dt.datetime.fromtimestamp(clock.now, dt.UTC).isoformat(timespec="seconds"),
                        "screen": "Packing screen", "ref": "gid://shopify/Order/2", "title": "Order #2", "kind": "order"}]
    s._write()
    fresh = store_module.install(path, clock=lambda: clock.now + SHOWING_KEEP_S + 60)   # the start: read and swept at once
    kept = path.read_text()
    assert "Sam Carter" not in kept and "Order #1" not in kept and "Order #2" in kept
    assert [d["ref"] for d in fresh.done()] == ["gid://shopify/Order/2"]


def _tool_session():
    from app.objectives import tools as objective_tools  # noqa: F401  registers the tools
    from app.session.models import Session
    from app.tools import display_tools  # noqa: F401

    return Session(session_id="screens-b05")


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
def test_an_objective_goes_up_only_once_this_conversation_was_shown_it(s, tmp_path):
    """Round 6, B-05, through the real dispatcher: objective_id had no issued-id rule, so any
    objective could be put on any screen. Now it is refused until the conversation has been
    shown it (objective_list here), like an order."""
    from app.objectives import store as objectives_store
    from app.tools.dispatch import dispatch

    objectives = objectives_store.install(tmp_path / "objectives-store")
    obj = objectives.create(title="Get the drop live", request="Get the SS26 drop live by Friday")
    screen = pair(s, "Office screen")
    session = _tool_session()

    refused = run(dispatch("screen_show", {"screen": "Office screen", "objective_id": obj.id}, session=session, timeout_s=5))
    assert refused.startswith("NOT YET") and "not an id this conversation has looked up" in refused
    assert s._data["screens"][screen["id"]]["showing"] is None
    for forged in ("obj_zz", "../../etc/passwd", "gid://shopify/Order/1"):
        text = run(dispatch("screen_show", {"screen": "Office screen", "objective_id": forged}, session=session, timeout_s=5))
        assert text.startswith("REFUSED"), text
    assert s._data["screens"][screen["id"]]["showing"] is None

    listed = run(dispatch("objective_list", {}, session=session, timeout_s=5))
    assert obj.id in listed
    shown = run(dispatch("screen_show", {"screen": "Office screen", "objective_id": obj.id}, session=session, timeout_s=5))
    assert "Get the drop live" in shown and not shown.startswith(("REFUSED", "NOT YET", "ERROR"))
    assert s._data["screens"][screen["id"]]["showing"]["ref"] == obj.id


def test_a_slip_goes_only_to_the_screen_named_in_full(s, monkeypatch):
    """Round 6, B-05: a spoken part of a name found the nearest screen. What goes up can be a
    customer's name and address, so screen_show takes the screen's own name or nothing."""
    from app.tools import display_tools, shopify_tools

    monkeypatch.setattr(shopify_tools, "_hydrator", FakeHydrator())
    office = pair(s, "Office screen")
    pair(s, "Office mac")
    for near in ("office", "screen", "offic screen", "Office screen please"):
        with pytest.raises(ToolError, match="Say its full name: Office mac, Office screen"):
            run(display_tools.screen_show(screen=near, order_id="gid://shopify/Order/1047"))
    assert all(x["showing"] is None for x in s.screens())
    out = run(display_tools.screen_show(screen="  OFFICE   screen ", order_id="gid://shopify/Order/1047"))
    assert out["screen"] == "Office screen" and s._data["screens"][office["id"]]["showing"]["kind"] == "order"


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
def test_a_list_is_refused_before_anything_is_done_with_it(s, monkeypatch):
    """Round 6, B-05: `lines` had no bounds and was walked whole before 40 were kept. The schema
    now says so, and the tool refuses before it looks for a screen or reads a line."""
    from app.tools import display_tools
    from app.tools.dispatch import dispatch
    from app.tools.registry import get

    schema = get("screen_show").input_schema["properties"]["lines"]
    assert schema["maxItems"] == views.MAX_LINES and schema["items"]["maxLength"] == views.MAX_LINE
    pair(s, "Office screen")

    def untouched(*_a, **_k):
        raise AssertionError("reached before the bounds were checked")

    monkeypatch.setattr(views, "list_view", untouched)
    monkeypatch.setattr(display_tools, "store", untouched)
    session = _tool_session()
    for lines, why in (
        (["a"] * (views.MAX_LINES + 1), "at most 40 lines"),
        (["a" * (views.MAX_LINE + 1)], "at most 200 characters"),
        ([{"text": "a"}], "short text"),
        ("not a list", "at most 40 lines"),
    ):
        text = run(dispatch("screen_show", {"screen": "Office screen", "title": "T", "lines": lines}, session=session, timeout_s=5))
        assert text.startswith("ERROR") and why in text, text
    text = run(dispatch("screen_show", {"screen": "Office screen", "title": "t" * 500, "lines": ["a"]}, session=session, timeout_s=5))
    assert text.startswith("ERROR") and "at most 120 characters" in text


# --------------------------------------------------------------------------- round 7, B-03


def test_the_done_record_keeps_no_ones_words(tmp_path):
    """Round 7, B-03: a done row and the slip it leaves kept the view's title and reference, and
    a list's or objective's title is the owner's own text, which can name a customer. Only an
    order's number, or the kind, is kept."""
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    screen = pair(s, "Office screen")
    key = screen["screen_key"]
    for view, title, ref in (
        (views.list_view("Sam Carter's alterations", ["Hem the trousers"]), "List", ""),
        (views.objective_view({"id": "obj_0123abcd", "title": "Call Sam Carter back"}, []), "Objective", "obj_0123abcd"),
        (views.order_view(ORDER), "Order #1047", "gid://shopify/Order/1047"),
        ({"kind": "order", "ref": "Sam Carter", "title": "Order for Sam Carter"}, "Order", ""),
    ):
        s.show(screen["id"], view)
        ack_all(s, screen["id"], key)
        s.mark_done(screen["id"], s.poll(screen["id"], key)["version"], screen_key=key, confirmed=True)
        row = s.done()[0]
        assert (row["title"], row["ref"]) == (title, ref)
        assert s.poll(screen["id"], key)["showing"]["title"] == title
    stored = path.read_text()
    assert "Sam Carter" not in stored and "Hem the trousers" not in stored


def test_a_change_that_could_not_be_written_is_not_made(tmp_path, monkeypatch):
    """Round 7, B-03: _save swallowed every failure and did not flush the folder, so a change
    could look made in memory while the disk said otherwise. The folder is flushed, and a failed
    write puts the record back and refuses the change.

    Round 8, B-03 changed the last part of this test, which asserted that CLEARING a slip is
    reported done when the folder could not be flushed after the record was put in place: that
    is a privacy deletion said done before it was durable, which is the finding. It is now made
    (the record is the file, and the purge journal keeps it) but answered NotDurable, and the
    next pass settles it. A change that deletes nothing keeps the old behaviour, below."""
    path = tmp_path / "displays.json"
    s = DisplayStore(path)
    screen = pair(s, "Office screen")
    flushed: list[str] = []
    real = store_module._fsync_dir
    real_replace = store_module.os.replace
    monkeypatch.setattr(store_module, "_fsync_dir", lambda folder: (flushed.append(str(folder)), real(folder)))
    s.show(screen["id"], views.list_view("Today", ["One"]))
    assert flushed == [str(path.parent)], "the folder is flushed after the file is renamed into place"
    before = path.read_bytes()

    # The record could not be put in place: nothing changed, in memory or on disk.
    monkeypatch.setattr(store_module.os, "replace", lambda *a: (_ for _ in ()).throw(OSError(28, "No space left")))
    with pytest.raises(store_module.NotSaved):
        s.show(screen["id"], views.order_view(ORDER))
    assert s.poll(screen["id"], screen["screen_key"])["showing"]["title"] == "Today", "memory put back as it was"
    assert path.read_bytes() == before and not list(path.parent.glob(".displays.json.*.tmp")), "no temporary left behind"
    assert not list(path.parent.glob(".*.tmp")) and not s.journal_path.exists(), "nor a journal"
    monkeypatch.setattr(store_module.os, "replace", real_replace)

    # In place, but the folder could not be flushed. Clearing the slip is a deletion: it stands
    # (it is the file, and the journal holds it) but it is not said done.
    def broken(folder):
        raise OSError(5, "I/O error")

    monkeypatch.setattr(store_module, "_fsync_dir", broken)
    with pytest.raises(NotDurable, match="could not make sure it is saved"):
        s.show(screen["id"], None)
    assert s._data["screens"][screen["id"]]["showing"] is None and s.journal_path.exists()
    assert s.unsaved and s.sweep() == "the screens record could not be made durable on disk yet"
    monkeypatch.setattr(store_module, "_fsync_dir", real)
    assert s.sweep() == "" and not s.unsaved and not s.journal_path.exists()

    # A change that deletes nothing, in place with the folder unflushed: the change stands (it is
    # the file), and that it may not survive a power cut is said and put right on the next pass.
    monkeypatch.setattr(store_module, "_fsync_dir", broken)
    s.show(screen["id"], views.list_view("Tomorrow", ["Two"]))
    assert s.unsaved and s.sweep() == "the screens record could not be made durable on disk yet"
    monkeypatch.setattr(store_module, "_fsync_dir", real)
    assert s.sweep() == "" and not s.unsaved


def test_a_slip_taken_down_stays_down_and_its_removal_is_retried_until_it_is_on_disk(tmp_path, monkeypatch):
    """Round 7, B-03: expiry could appear to succeed in memory while the slip stayed on disk. A slip
    past its time is never shown again; if its removal cannot be written, the store says so (the
    housekeeping pass reports it on /health) and writes it on the next pass that can."""
    import datetime as dt

    from app.main import housekeep_once

    clock = Clock()
    monkeypatch.setattr(store_module, "_now_iso", lambda: dt.datetime.fromtimestamp(clock.now, dt.UTC).isoformat(timespec="seconds"))
    path = tmp_path / "objectives" / "displays.json"
    s = store_module.install(path, clock=clock)
    screen = pair(s, "Packing screen")
    s.show(screen["id"], views.order_view(ORDER))
    clock.now += SHOWING_KEEP_S + 60
    real_write = DisplayStore._write
    monkeypatch.setattr(DisplayStore, "_write", lambda self: (_ for _ in ()).throw(OSError(28, "No space left")))
    assert s.poll(screen["id"], screen["screen_key"])["showing"] is None, "down, even though the disk could not be told"
    problem = housekeep_once(object())
    assert "could not yet be removed from disk" in problem and s.unsaved
    assert "Sam Carter" in path.read_text(), "still on disk: which is exactly what is being reported"
    monkeypatch.setattr(DisplayStore, "_write", real_write)
    assert housekeep_once(object()) == "" and not s.unsaved
    assert "Sam Carter" not in path.read_text()


def test_the_screens_route_says_a_change_was_not_saved(s, monkeypatch):
    client = app_with(s, local_owner=True)
    made = client.post("/displays/register", json={"name": "Packing screen"}, headers=OWNER).json()
    monkeypatch.setattr(DisplayStore, "_write", lambda self: (_ for _ in ()).throw(OSError(28, "No space left")))
    refused = client.post("/displays/register", json={"name": "Kitchen screen"}, headers=OWNER)
    assert refused.status_code == 503 and refused.json()["code"] == "not_saved"
    assert [x["name"] for x in s.screens()] == ["Packing screen"] and made["id"]


# --------------------------------------------------------------------------- round 8, B-01


def test_the_screen_tools_answer_only_the_owners_own_request(s):
    """Round 8, B-01: neither screen tool checked who it was running for; the shared boundary
    admits any live service authority. Each handler now requires the owner's own: a service
    authority derived from his — a speculative read his request started — is refused by every
    screen tool, while it is live and after his authority is revoked, and no authority at all is
    refused too. Through the dispatcher the same calls come back refused or as an error, and
    nothing reaches a screen."""
    from app.tools import display_tools
    from app.tools.dispatch import dispatch

    screen = pair(s, "Office screen")
    waiting = s.register("Packing screen")
    held = owner()
    service = held.derive("prefetch:screens", 60)
    assert service is not None and service.kind == authority.SERVICE

    def calls():
        return (
            display_tools.screen_list(),
            display_tools.screen_show(screen="Office screen", title="From a prefetch", lines=["one"]),
            display_tools.screen_pair(screen="Packing screen", code=waiting["code"]),
        )

    def refused_everywhere(who):
        for call in calls():
            with pytest.raises(ToolError, match="only the owner's own request"):
                run(call, held=who)

    with owner_saying(f"approve the packing screen, code {waiting['code']}"):
        refused_everywhere(service)
        refused_everywhere(None)
        held.revoke()                                   # the owner's request has been answered
        assert service.active, "the service authority outlives it by design"
        refused_everywhere(service)
        session = _tool_session()
        session.heard = f"approve the packing screen, code {waiting['code']}"
        for tool, args in (("screen_list", {}),
                           ("screen_show", {"screen": "Office screen", "title": "From a prefetch", "lines": ["one"]}),
                           ("screen_pair", {"screen": "Packing screen", "code": waiting["code"]})):
            text = run(dispatch(tool, args, session=session, timeout_s=5), held=service)
            assert text.startswith(("REFUSED", "ERROR")), text
    assert s._data["screens"][screen["id"]]["showing"] is None
    assert s._data["screens"][waiting["id"]]["paired"] is False, "not approved by service work"
    # The owner's own request is answered.
    assert [x["name"] for x in run(display_tools.screen_list())["screens"]] == ["Office screen", "Packing screen"]


# --------------------------------------------------------------------------- round 8, B-02 and B-05


def test_a_competing_first_registration_is_shown_nothing_until_the_owner_approves_it(tmp_path):
    """Round 8, B-02 and B-05: first registration had no pairing step, so any device the owner
    rule admits could claim an intended name first and be sent its slips. A new name now waits
    for approval with a code only that device shows; nothing is put on it until the owner says
    that code; and the device he means can have the name once he removes the other's request."""
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    rogue = s.register("Packing screen")             # an admitted device that is not the one meant
    assert rogue["pending"] is True and re.fullmatch(r"\d{6}", rogue["code"])
    text = path.read_text()
    assert rogue["screen_key"] not in text and f'"{rogue["code"]}"' not in text, "only hashes are kept"
    with pytest.raises(NotPaired, match="hasn't been approved yet"):
        s.show(rogue["id"], views.order_view(ORDER))
    polled = s.poll(rogue["id"], rogue["screen_key"])
    assert polled["pending"] is True and polled["showing"] is None and PAIR_CODE_S - 5 <= polled["code_expires_in"] <= PAIR_CODE_S
    for step in (lambda: s.acknowledge(rogue["id"], 0, screen_key=rogue["screen_key"], start=0, end=1),
                 lambda: s.mark_done(rogue["id"], 0, screen_key=rogue["screen_key"], confirmed=True)):
        with pytest.raises(NotPaired):
            step()
    assert "Sam Carter" not in path.read_text()
    # The device the owner means cannot take the name while the other waits...
    with pytest.raises(NameTaken, match="waiting to be approved"):
        s.register("packing screen")
    # ...so he removes that request (it never showed anything) and names the right device.
    assert s.forget(rogue["id"]) is True
    mine = s.register("Packing screen")
    wrong = next(c for c in ("000000", "111111") if c != mine["code"])
    with pytest.raises(DisplayError, match="not the code on the Packing screen, so it was not approved. 4 tries left"):
        s.approve("Packing screen", wrong)
    if rogue["code"] != mine["code"]:
        with pytest.raises(DisplayError, match="not the code"):
            s.approve("Packing screen", rogue["code"])
    # The code he reads off the screen he means, spaced as it is shown.
    assert s.approve("packing SCREEN", mine["code"][:3] + " " + mine["code"][3:]) == {"screen": "Packing screen", "approved": True}
    s.show(mine["id"], views.order_view(ORDER))
    assert s.poll(mine["id"], mine["screen_key"])["showing"]["kind"] == "order"
    assert s.poll(rogue["id"], rogue["screen_key"]) is None, "the other device's key is nothing now"
    assert s.approve("Packing screen", mine["code"])["note"] == "It was already approved."
    with pytest.raises(DisplayError, match="six digits"):
        s.approve("Packing screen", "12 34")


def test_five_wrong_codes_cancel_the_request_and_free_the_name(tmp_path):
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    made = s.register("Office screen")
    wrongs = [c for c in ("000000", "111111", "222222", "333333", "444444", "555555") if c != made["code"]][:PAIR_TRIES]
    with pytest.raises(DisplayError, match="six digits"):
        s.approve("Office screen", "12345")          # not a code at all: not counted
    for n, code in enumerate(wrongs[:-1], 1):
        with pytest.raises(DisplayError, match=f"{PAIR_TRIES - n} tr"):
            s.approve("Office screen", code)
    # The count is written down: a restart gives no more tries.
    s = DisplayStore(path, mono=Tick())
    with pytest.raises(DisplayError, match=f"That was the {PAIR_TRIES}th wrong code, so the request for the Office screen is cancelled"):
        s.approve("Office screen", wrongs[-1])
    assert s.poll(made["id"], made["screen_key"]) is None
    with pytest.raises(DisplayError, match="no screen called 'Office screen' waiting to be approved"):
        s.approve("Office screen", made["code"])
    assert DisplayStore(path).get(made["id"]) is None, "cancelled for good, across a restart"
    again = s.register("Office screen")
    assert again["id"] != made["id"] and again["pending"] is True


def test_a_code_that_runs_out_frees_the_name_and_its_screen_was_never_shown_anything(tmp_path):
    clock = Clock()
    path = tmp_path / "displays.json"
    s = DisplayStore(path, clock=clock, mono=Tick())
    made = s.register("Office screen")
    clock.now += PAIR_CODE_S + 1
    with pytest.raises(DisplayError, match="ran out before it was approved"):
        s.approve("Office screen", made["code"])
    assert s.poll(made["id"], made["screen_key"]) is None
    # With nobody approving: the next pass, ask or naming cancels it, and the name is free.
    other = s.register("Packing screen")
    clock.now += PAIR_CODE_S + 1
    assert s.sweep() == "" and s.get(other["id"]) is None
    third = s.register("Bedroom TV")
    clock.now += PAIR_CODE_S + 1
    taken = s.register("Bedroom TV")
    assert taken["id"] != third["id"] and taken["pending"] is True
    assert "Sam Carter" not in path.read_text()


def test_a_request_waiting_for_approval_survives_a_restart_as_it_was(tmp_path):
    clock = Clock()
    path = tmp_path / "displays.json"
    s = DisplayStore(path, clock=clock, mono=Tick())
    made = s.register("Office screen")
    wrong = next(c for c in ("000000", "111111") if c != made["code"])
    with pytest.raises(DisplayError, match="4 tries left"):
        s.approve("Office screen", wrong)
    restarted = DisplayStore(path, clock=clock, mono=Tick())
    polled = restarted.poll(made["id"], made["screen_key"])
    assert polled["pending"] is True and polled["showing"] is None
    with pytest.raises(NotPaired):
        restarted.show(made["id"], views.list_view("Today", ["One"]))
    with pytest.raises(NameTaken, match="waiting to be approved"):
        restarted.register("Office screen")
    with pytest.raises(DisplayError, match="3 tries left"):
        restarted.approve("Office screen", wrong)
    # Its page opened again: the device holding its key asks for a new code (the old one no
    # longer approves it), and is still waiting.
    renewed = restarted.register("Office screen", screen_key=made["screen_key"])
    assert renewed["id"] == made["id"] and renewed["pending"] is True and renewed["screen_key"] != made["screen_key"]
    if renewed["code"] != made["code"]:
        with pytest.raises(DisplayError, match="not the code"):
            restarted.approve("Office screen", made["code"])
    assert restarted.approve("Office screen", renewed["code"])["approved"] is True
    restarted.show(made["id"], views.list_view("Today", ["One"]))
    assert restarted.poll(made["id"], renewed["screen_key"])["showing"]["title"] == "Today"


def test_a_screen_written_down_before_approval_existed_counts_as_approved(tmp_path):
    path = tmp_path / "displays.json"
    key = "a-key-from-before-round-8"
    path.write_text(json.dumps({"screens": {"scr_0123456789ab": {
        "id": "scr_0123456789ab", "name": "Office screen", "key": "office screen", "secret": store_module._key_hash(key),
        "created_at": "2026-09-26T10:00:00+00:00", "last_seen": "2026-09-26T10:00:00+00:00", "version": 3, "showing": None}},
        "done": []}), encoding="utf-8")
    s = DisplayStore(path)
    s.show("scr_0123456789ab", views.list_view("Today", ["One"]))
    polled = s.poll("scr_0123456789ab", key)
    assert polled["pending"] is False and polled["showing"]["title"] == "Today"


def test_screen_pair_approves_only_with_the_code_the_owner_said(s):
    """Round 8, B-02: the code is the owner's proof that he is looking at the device he means, so
    screen_pair takes it only from his own words in the request being answered — never from an
    email, an order note or a guess — and a code he did not say is not even counted."""
    from app.tools import display_tools

    made = s.register("Office screen")
    code = made["code"]
    digits = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    for heard in ("", "approve the office screen", "put order 1047 on the office screen"):
        with owner_saying(heard), pytest.raises(ToolError, match="reads out from it himself"):
            run(display_tools.screen_pair(screen="Office screen", code=code))
    with pytest.raises(ToolError, match="reads out from it himself"):
        run(display_tools.screen_pair(screen="Office screen", code=code))      # no request at all
    assert s._data["screens"][made["id"]]["pairing"]["tries"] == 0 and s._data["screens"][made["id"]]["paired"] is False
    with owner_saying("approve it"), pytest.raises(ToolError, match="six digits"):
        run(display_tools.screen_pair(screen="Office screen", code="12"))
    # A screen waiting for approval is shown nothing, whatever CLIVE is asked to put on it.
    with pytest.raises(ToolError, match="hasn't been approved yet"):
        run(display_tools.screen_show(screen="Office screen", title="T", lines=["a"]))
    listed = run(display_tools.screen_list())
    assert listed["screens"][0]["pending"] is True and "six-digit code" in listed["note"]
    assert code not in json.dumps(listed), "the code is never said back"
    # Said as the transcript writes it, digits as words.
    with owner_saying("approve the office screen code " + " ".join(digits[int(d)] for d in code)):
        out = run(display_tools.screen_pair(screen="office screen", code=f"{code[:3]} {code[3:]}"))
    assert out == {"screen": "Office screen", "approved": True}
    out = run(display_tools.screen_show(screen="Office screen", title="T", lines=["a"]))
    assert out["showing"] == "T"
    # A name that does not end in "screen", said as the screen's page puts it.
    tv = s.register("Bedroom TV")
    with owner_saying(f"approve the bedroom tv screen, code {tv['code'][:3]} {tv['code'][3:]}"):
        assert run(display_tools.screen_pair(screen="bedroom tv screen", code=tv["code"])) == {"screen": "Bedroom TV", "approved": True}
    page = (WEB / "display.js").read_text(encoding="utf-8")
    assert "'Tell CLIVE: “approve the ' + saidName(S.screen.name) + ', code ' + code + '”'" in page
    assert "return /\\bscreen$/.test(n) ? n : n + ' screen';" in page


# --------------------------------------------------------------------------- round 8, NEW-B-CAP


def test_at_the_most_screens_a_new_name_is_refused_and_nothing_is_removed(tmp_path):
    """Round 8, NEW-B-CAP. This replaces test_the_oldest_screen_makes_way_when_there_are_too_many,
    which asserted the behaviour the finding says is wrong: at MAX_SCREENS a new name silently
    deleted the least recently seen screen, its key and its live slip, and freed its name for
    another device. Now the new name is refused (409 too_many_screens, telling the owner to
    remove one first) and nothing is removed; the screen with a live slip keeps it, and its name
    cannot be claimed, before or after a restart; only the owner removing a screen makes room."""
    clock = Clock()
    path = tmp_path / "objectives" / "displays.json"
    s = store_module.install(path, clock=clock, mono=Tick())
    first = pair(s, "Screen 0")
    s.show(first["id"], views.order_view(ORDER))    # a live slip, on the screen seen longest ago
    for i in range(1, MAX_SCREENS):
        clock.now += 120
        pair(s, f"Screen {i}")
    clock.now += 120
    with pytest.raises(TooMany, match="Remove one you no longer use first"):
        s.register("One more")
    names = {x["name"] for x in s.screens()}
    assert len(names) == MAX_SCREENS and "One more" not in names and "Screen 0" in names
    assert s.poll(first["id"], first["screen_key"])["showing"]["order"]["customer"] == "Sam Carter", "the slip is still up"
    for store in (s, DisplayStore(path, clock=clock, mono=Tick())):
        with pytest.raises(NameTaken):
            store.register("screen 0")
        with pytest.raises(NameTaken):
            store.register("Screen 0", screen_key="guess")
    client = app_with(s)
    refused = client.post("/displays/register", json={"name": "One more"}, headers=OWNER)
    assert refused.status_code == 409 and refused.json()["code"] == "too_many_screens"
    assert "Remove one" in refused.json()["detail"]
    assert "Sam Carter" in path.read_text()
    # A request waiting for approval takes a place too, until it is approved, cancelled or runs out.
    assert client.post("/displays/forget", json={"name": "Screen 7"}, headers=OWNER).json() == {"forgotten": "Screen 7"}
    waiting = client.post("/displays/register", json={"name": "One more"}, headers=OWNER).json()
    assert waiting["pending"] is True
    with pytest.raises(TooMany):
        s.register("Yet another")
    clock.now += PAIR_CODE_S + 1
    assert s.register("Yet another")["pending"] is True, "a request that ran out gave its place back"
    assert s.poll(first["id"], first["screen_key"])["showing"]["order"]["customer"] == "Sam Carter"


# --------------------------------------------------------------------------- round 8, B-03


def _flaky_record_flush(monkeypatch, *, fail_from: int):
    """The folder flushes work until the `fail_from`th (1-based) from now, and fail from then on
    (the disk has gone bad); the replaces are recorded in order."""
    real_flush = store_module._fsync_dir
    real_replace = store_module.os.replace
    calls = {"flush": 0}
    placed: list[str] = []

    def flush(folder):
        calls["flush"] += 1
        if calls["flush"] >= fail_from:
            raise OSError(5, "I/O error")
        real_flush(folder)

    def replace(src, dst):
        placed.append(Path(dst).name)
        real_replace(src, dst)

    monkeypatch.setattr(store_module, "_fsync_dir", flush)
    monkeypatch.setattr(store_module.os, "replace", replace)
    return placed, lambda: (monkeypatch.setattr(store_module, "_fsync_dir", real_flush),
                            monkeypatch.setattr(store_module.os, "replace", real_replace))


def test_a_packed_slip_whose_record_is_not_durable_is_not_said_done_and_does_not_come_back(tmp_path, monkeypatch):
    """Round 8, B-03: a folder flush that failed AFTER the record was renamed into place let
    mark_done answer success while the slip's removal lived only in memory; a power cut before the
    retry, and the restart restored the customer's slip. Now the deletion is written to the purge
    journal (flushed, with its folder) before the record; the caller is told it is not saved yet;
    and on the restart the journal is applied before anything else."""
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    screen = pair(s, "Packing screen")
    key = screen["screen_key"]
    s.show(screen["id"], views.order_view(ORDER))
    ack_all(s, screen["id"], key)
    durable = path.read_bytes()                        # what is safely on disk: the whole slip
    assert b"Sam Carter" in durable
    placed, restore = _flaky_record_flush(monkeypatch, fail_from=2)   # the journal's flush works; the record's does not
    with pytest.raises(NotDurable):
        s.mark_done(screen["id"], 1, screen_key=key, confirmed=True)
    assert placed == ["displays.purge.json", "displays.json"], "the journal is in place before the record"
    journal = s.journal_path.read_text()
    assert stat.S_IMODE(os.stat(s.journal_path).st_mode) == 0o600
    for gone in ("Sam Carter", "E8 1AA", "Sample Road", "gift", "HW-TEE"):
        assert gone not in journal, gone
    # The deletion stands (the screen asks and is told it is done, version 2); tapped again
    # before anything is durable, it is still not said done.
    assert s.poll(screen["id"], key)["version"] == 2
    with pytest.raises(NotDurable):
        s.mark_done(screen["id"], 2, screen_key=key, confirmed=True)
    restore()
    # The power goes before the retry: the record's rename never reached the disk.
    path.write_bytes(durable)
    restarted = DisplayStore(path, mono=Tick())
    kept = path.read_text()
    for gone in ("Sam Carter", "E8 1AA", "Sample Road", "gift", "HW-TEE"):
        assert gone not in kept, gone
    showing = restarted.poll(screen["id"], key)["showing"]
    assert showing["done_at"] and showing["title"] == "Order #1047" and "order" not in showing
    assert [d["ref"] for d in restarted.done()] == [ORDER["order_id"]], "what was packed is still recorded, once"
    assert not restarted.journal_path.exists(), "applied, written down durably, and gone"
    assert DisplayStore(path).done() == restarted.done(), "a second start changes nothing"


def test_the_done_route_answers_503_until_the_deletion_is_durable(s, monkeypatch):
    client = app_with(s)
    screen = pair(s, "Packing screen")
    mine = {**OWNER, "X-Screen-Key": screen["screen_key"]}
    s.show(screen["id"], views.list_view("Sam Carter's alterations", ["Hem the trousers"]))
    ack_all(s, screen["id"], screen["screen_key"])
    _placed, restore = _flaky_record_flush(monkeypatch, fail_from=2)
    answer = client.post(f"/displays/{screen['id']}/done", json={"version": 1, "confirm": True}, headers=mine)
    assert answer.status_code == 503 and answer.json()["code"] == "not_saved"
    restore()
    again = client.post(f"/displays/{screen['id']}/done", json={"version": 2, "confirm": True}, headers=mine)
    assert again.status_code == 200 and again.json()["showing"]["done_at"]
    assert not s.journal_path.exists() and "Hem the trousers" not in s.path.read_text()


def test_a_removed_screen_and_a_cleared_slip_do_not_come_back_after_a_restart(tmp_path, monkeypatch):
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    gone = pair(s, "Office screen")
    cleared = pair(s, "Packing screen")
    s.show(gone["id"], views.order_view(ORDER))
    s.show(cleared["id"], views.list_view("Sam Carter's alterations", ["Hem the trousers"]))
    durable = path.read_bytes()
    _placed, restore = _flaky_record_flush(monkeypatch, fail_from=2)
    with pytest.raises(NotDurable):
        s.forget(gone["id"])
    restore()
    _placed, restore = _flaky_record_flush(monkeypatch, fail_from=2)
    with pytest.raises(NotDurable):
        s.show(cleared["id"], None)
    restore()
    path.write_bytes(durable)                          # neither rename reached the disk
    restarted = DisplayStore(path, mono=Tick())
    assert restarted.get(gone["id"]) is None and restarted.poll(gone["id"], gone["screen_key"]) is None
    assert restarted.poll(cleared["id"], cleared["screen_key"])["showing"] is None
    kept = path.read_text()
    assert "Sam Carter" not in kept and "Hem the trousers" not in kept and not restarted.journal_path.exists()


def test_a_deletion_whose_journal_cannot_be_written_is_not_made(tmp_path, monkeypatch):
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    screen = pair(s, "Packing screen")
    s.show(screen["id"], views.order_view(ORDER))
    before = path.read_bytes()
    real_put = DisplayStore._put

    def no_journal(self, target, text):
        if target == self.journal_path:
            raise OSError(28, "No space left")
        return real_put(self, target, text)

    monkeypatch.setattr(DisplayStore, "_put", no_journal)
    with pytest.raises(NotSaved, match="nothing was changed"):
        s.show(screen["id"], None)
    assert s.poll(screen["id"], screen["screen_key"])["showing"]["title"] == "Order #1047"
    assert path.read_bytes() == before and not s.journal_path.exists()


def test_a_journal_that_cannot_be_read_takes_every_slip_down(tmp_path):
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    screen = pair(s, "Packing screen")
    s.show(screen["id"], views.order_view(ORDER))
    s.journal_path.write_text("{not a journal", encoding="utf-8")
    restarted = DisplayStore(path, mono=Tick())
    assert restarted.poll(screen["id"], screen["screen_key"])["showing"] is None
    assert "Sam Carter" not in path.read_text() and not restarted.journal_path.exists()
    # And one that is tampered with cannot put a customer back.
    restarted.show(screen["id"], views.list_view("Today", ["One"]))
    version = restarted.poll(screen["id"], screen["screen_key"])["version"]
    restarted.journal_path.write_text(json.dumps({"screens": {screen["id"]: {
        "version": version + 1, "showing": views.order_view(ORDER)}}}), encoding="utf-8")
    third = DisplayStore(path, mono=Tick())
    assert third.poll(screen["id"], screen["screen_key"])["showing"] is None and "Sam Carter" not in path.read_text()


# --------------------------------------------------------------------------- round 8, B-04


def test_pages_are_told_in_order_one_size_and_not_too_fast_and_done_needs_the_tap(s):
    """Round 8, B-04: /seen took any range the key-holding screen sent, so a client that never
    drew a page could acknowledge a whole order in a burst and say done. Now, straight at the
    routes: a page must carry on from where the last ended (not skip ahead, not overlap), every
    page but the last is the same size, a new page comes at least a second after the last, and
    done needs every item, a second's look at the last page, and the tap's own confirm. This
    still rests on the screen's own word — the key-holder can pace itself — and that residual
    is the owner's ruling."""
    client = app_with(s)
    screen = pair(s, "Packing screen")
    mine = {**OWNER, "X-Screen-Key": screen["screen_key"]}
    many = dict(ORDER, items=[dict(ORDER["items"][1], title=f"Tee {i}", sku=f"SKU-{i}") for i in range(25)])
    s.show(screen["id"], views.order_view(many))

    def seen(start, end, version=1):
        return client.post(f"/displays/{screen['id']}/seen", json={"version": version, "start": start, "end": end}, headers=mine)

    def done(body):
        return client.post(f"/displays/{screen['id']}/done", json=body, headers=mine)

    skipped = seen(10, 20)
    assert skipped.status_code == 409 and skipped.json()["code"] == "out_of_order" and skipped.json()["covered"] == 0
    assert seen(0, 13).json()["code"] == "refused", "a page is 12 items at most"
    assert seen(0, 10).json() == {"seen": 10}
    hurried = seen(10, 20)
    assert hurried.status_code == 409 and hurried.json()["code"] == "too_soon" and 0 < hurried.json()["retry_after_ms"] <= 1000
    later(s)
    for start, end in ((5, 15), (12, 22), (10, 18)):   # overlapping, leaving a gap, another size
        refused = seen(start, end)
        assert refused.status_code == 409 and refused.json()["code"] == "out_of_order", (start, end)
    # A page already told, told again, changes nothing and waits for nothing.
    assert seen(0, 10).json() == {"seen": 10} and seen(3, 8).json() == {"seen": 10}
    assert seen(10, 20).json() == {"seen": 20}
    later(s)
    for body in ({"version": 1}, {"version": 1, "confirm": False}):
        refused = done(body)
        assert refused.status_code == 409 and refused.json()["code"] == "not_confirmed"
    for body in ({"version": 1, "confirm": "true"}, {"version": 1, "confirm": 1}):
        assert done(body).status_code == 422, "only the JSON value true is the tap"
    unseen = done({"version": 1, "confirm": True})
    assert unseen.status_code == 409 and unseen.json()["code"] == "not_seen"
    assert seen(20, 25).json() == {"seen": 25}, "the last page may be shorter"
    hurried = done({"version": 1, "confirm": True})
    assert hurried.status_code == 409 and hurried.json()["code"] == "too_soon" and hurried.json()["retry_after_ms"] > 0
    assert s.done() == []
    later(s)
    packed = done({"version": 1, "confirm": True})
    assert packed.status_code == 200 and packed.json()["showing"]["done_at"]
    assert s.done()[0]["by"] == OWNER_LOGIN


def test_a_screen_that_lays_its_pages_out_again_starts_the_count_again(s):
    """A resize changes how many rows a page holds (web/display.js fitPage): a first page of a
    new size starts the count from nothing, and nothing already counted carries over."""
    screen = pair(s, "Packing screen")
    key = screen["screen_key"]
    many = dict(ORDER, items=[dict(ORDER["items"][1], title=f"Tee {i}", sku=f"SKU-{i}") for i in range(20)])
    s.show(screen["id"], views.order_view(many))
    later(s)
    assert s.acknowledge(screen["id"], 1, screen_key=key, start=0, end=10) == 10
    later(s)
    assert s.acknowledge(screen["id"], 1, screen_key=key, start=0, end=5) == 5, "a new layout: from the first again"
    for start in (5, 10, 15):
        later(s)
        s.acknowledge(screen["id"], 1, screen_key=key, start=start, end=start + 5)
    later(s)
    s.mark_done(screen["id"], 1, screen_key=key, confirmed=True)
    assert len(s.done()) == 1


def test_the_page_tells_pages_in_order_waits_when_told_and_confirms_only_from_the_tap():
    src = (WEB / "display.js").read_text(encoding="utf-8")
    assert src.count("confirm: true") == 1
    tap = src[src.index("async function markDone("):src.index("// ---- asking CLIVE what to show")]
    assert "JSON.stringify({ version: S.version, confirm: true })" in tap
    assert "why.code === 'too_soon'" in tap and "why.retry_after_ms" in tap
    pump = src[src.index("function ackPage() {"):src.index("function heardAll(")]
    assert "data.code === 'too_soon') { ackLater(data.retry_after_ms)" in pump
    assert "const start = ACK.covered;" in pump and "!PAGE.seen.has(start / PAGE.per)" in pump


# --------------------------------------------------------------------------- round 8, NEW-B-LOCAL-SLIP


def test_the_screen_takes_a_customer_off_at_once_when_it_may_no_longer_show_it():
    """Round 8, NEW-B-LOCAL-SLIP: an open screen kept its slip on a 403 or a lost connection, and
    only a done slip ever timed out, so taking a login off the list, or CLIVE's own expiry, could
    not take a customer's details off a screen left open. Now (tests/web/display.test.js runs it):
    a 403 wipes the page, the dots that drew it and what is kept of it at once, and says so
    plainly; so does two minutes out of reach; and a slip older than CLIVE's own limit comes
    down here even if CLIVE is never heard from."""
    src = (WEB / "display.js").read_text(encoding="utf-8")
    poll = src[src.index("async function poll() {"):src.index("function wipe(why) {")]
    refused = poll[poll.index("if (response.status === 403) {"):]
    assert refused.index("wipe('refused')") < refused.index("setTimeout(poll, REFUSED_MS)")
    assert "if (S.screen && !S.gone && Date.now() - S.lastOk >= OFFLINE_CLEAR_MS) wipe('offline');" in poll
    assert "const OFFLINE_CLEAR_MS = 120000;" in src and "ctl.abort(), POLL_TIMEOUT_MS" in poll
    wipe = src[src.index("function wipe(why) {"):]
    wipe = wipe[:wipe.index("\n  }\n") + 4]
    for step in ("S.showing = null", "S.drawnView = null", "S.version = -1", "draw(null)", "makeEngine();",
                 "E.idleNow(clockTargets())", "S.gen++"):
        assert step in wipe, step
    assert "This screen isn’t allowed to show CLIVE’s things any more." in src
    # CLIVE's own limit, from when it was put up, by CLIVE's clock.
    assert f"const SHOW_KEEP_MS = {SHOWING_KEEP_S // 3600} * 3600 * 1000;" in src
    assert "if (tooOld(s)) return null;" in src and "serverNow() - at > SHOW_KEEP_MS" in src
    # Losing the screen itself (404, or another device's key) wipes before it names itself again.
    assert "wipe('');\n    forgetScreen(); S.screen = null; toNaming();" in src
