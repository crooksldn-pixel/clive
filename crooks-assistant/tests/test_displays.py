"""The owner's screens: a device names itself at /display, CLIVE puts an order's slip, an
objective or a list on it by that name, and what is marked done there is CLIVE's own record.

What is held here: a name is one screen however it is typed, a spoken name finds it or is
answered plainly, what a screen shows moves only forward, a late tap never marks the wrong thing,
every route is the owner's alone, and the page is served without the data it draws."""

from __future__ import annotations

import asyncio
import os
import re
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.displays import store as store_module
from app.displays import views
from app.displays.store import (
    MAX_DONE,
    MAX_SCREENS,
    ONLINE_S,
    SHOWING_KEEP_S,
    DisplayError,
    DisplayStore,
    NotThisScreen,
)
from app.tools import gate
from app.tools.gate import Tier
from app.tools.registry import ToolError


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives" / "displays.json")


# --------------------------------------------------------------------------- the record


def test_a_name_is_one_screen_however_it_is_typed_and_the_device_that_named_it_holds_it(tmp_path):
    """Round 6, B-02: knowing a screen's name is not being that screen. Naming hands the device a
    key; the name cannot be taken while its screen is on; once it has gone quiet it can be named
    again from another device, and the old device's key stops fitting."""
    clock = Clock()
    s = DisplayStore(tmp_path / "displays.json", clock=clock)
    first = s.register("Office screen")
    key = first["screen_key"]
    assert len(key) >= 24 and "secret" not in first
    with pytest.raises(DisplayError, match="A screen called Office screen is on right now"):
        s.register("  office   SCREEN! ")
    assert s.poll(first["id"], key)["name"] == "Office screen"
    for wrong in ("", "guess", first["id"]):
        with pytest.raises(NotThisScreen):
            s.poll(first["id"], wrong)
    stored = (tmp_path / "displays.json").read_text()
    assert key not in stored, "only the key's hash is kept"
    clock.now += ONLINE_S + 1                       # the device lost its storage and went quiet
    again = s.register("  office   SCREEN! ")
    assert again["id"] == first["id"] and again["name"] == "Office screen" and again["screen_key"] != key
    with pytest.raises(NotThisScreen):
        s.poll(first["id"], key)
    assert s.poll(first["id"], again["screen_key"]) is not None
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
    screen = s.register("Office screen")
    key = screen["screen_key"]
    assert s.poll(screen["id"], key)["version"] == 0
    s.show(screen["id"], views.list_view("Today", ["One", "Two"]))
    shown = s.poll(screen["id"], key)
    assert shown["version"] == 1 and shown["showing"]["title"] == "Today" and shown["showing"]["at"]
    # A tap on what the screen drew before the change is refused, and nothing is recorded.
    with pytest.raises(DisplayError, match="changed before that tap"):
        s.mark_done(screen["id"], 0, screen_key=key, items_seen=2, by="team@crooksldn.com")
    # Nor from a device without the key, nor having seen only part of the list.
    with pytest.raises(NotThisScreen):
        s.mark_done(screen["id"], 1, screen_key="guess", items_seen=2)
    with pytest.raises(DisplayError, match="Not every line of the list was on the screen"):
        s.mark_done(screen["id"], 1, screen_key=key, items_seen=1)
    with pytest.raises(DisplayError, match="Not every line"):
        s.mark_done(screen["id"], 1, screen_key=key)
    assert s.done() == []
    s.mark_done(screen["id"], 1, screen_key=key, items_seen=2, by="team@crooksldn.com")
    after = s.poll(screen["id"], key)
    assert after["version"] == 2 and after["showing"]["done_at"]
    assert after["last_done"]["title"] == "Today"
    # A second tap on the same thing is the same record, not another.
    s.mark_done(screen["id"], 2, screen_key=key, items_seen=2)
    assert len(s.done()) == 1 and s.done()[0]["by"] == "team@crooksldn.com"
    # Clearing empties it.
    s.show(screen["id"], None)
    assert s.poll(screen["id"], key)["showing"] is None


def test_the_done_record_is_per_screen_and_bounded(s):
    a = s.register("Office screen")
    b = s.register("Packing screen")
    s.show(a["id"], {"kind": "order", "ref": "gid://shopify/Order/1", "title": "Order 1001"})
    s.mark_done(a["id"], 1, screen_key=a["screen_key"], items_seen=0)
    assert s.poll(b["id"], b["screen_key"])["last_done"] is None, "done on one screen is not done on another"
    assert s.done(ref="gid://shopify/Order/1")[0]["screen"] == "Office screen"
    for i in range(MAX_DONE + 5):
        s.show(b["id"], {"kind": "list", "ref": "", "title": f"List {i}"})
        s.mark_done(b["id"], s.poll(b["id"], b["screen_key"])["version"], screen_key=b["screen_key"], items_seen=0)
    assert len(s._data["done"]) == MAX_DONE


def test_the_oldest_screen_makes_way_when_there_are_too_many(tmp_path):
    clock = Clock()
    s = DisplayStore(tmp_path / "displays.json", clock=clock)
    first = s.register("Screen 0")
    for i in range(1, MAX_SCREENS):
        clock.now += 120
        s.register(f"Screen {i}")
    clock.now += 120
    s.register("One more")
    names = {x["name"] for x in s.screens()}
    assert len(names) == MAX_SCREENS and "One more" in names and first["name"] not in names


def test_the_record_is_private_on_disk_and_survives_a_restart(tmp_path):
    path = tmp_path / "objectives" / "displays.json"
    s = DisplayStore(path)
    screen = s.register("Office screen")
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


def run(coro):
    return asyncio.run(coro)


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
    s.register("Office screen")
    clock.now += 120   # it has not asked for anything since: it is off
    out = run(display_tools.screen_show(screen="office screen", order_id="gid://shopify/Order/1047"))
    assert out["screen"] == "Office screen" and out["showing"] == "Order #1047"
    assert fake.asked == ["gid://shopify/Order/1047"]
    assert out["on"] is False and "next on" in out["note"]
    showing = s._data["screens"][s.find("office")["id"]]["showing"]
    assert showing["kind"] == "order" and showing["order"]["customer"] == "Sam Carter" and showing["by"] == "clive"


def test_screen_show_takes_one_thing_and_names_the_screens_it_knows(s):
    from app.tools import display_tools

    s.register("Office screen")
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
    s.register("Office screen")
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
    screen = s.register("Packing screen")
    s.show(screen["id"], {"kind": "order", "ref": "gid://shopify/Order/1047", "title": "Order #1047"})
    s.poll(screen["id"], screen["screen_key"])   # the screen asked: it is on
    s.mark_done(screen["id"], 1, screen_key=screen["screen_key"], items_seen=0, by="team@crooksldn.com")
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


# --------------------------------------------------------------------------- the routes


def app_with(s, *, allowed=("team@crooksldn.com",), local_owner=False) -> TestClient:
    from app.routes import displays

    app = FastAPI()
    app.include_router(displays.router)
    settings = SimpleNamespace(writes_local_owner=local_owner, tailscale_verify=False, tailscale_cli="")
    app.state.runtime = SimpleNamespace(allowed_logins=allowed, settings=settings)
    return TestClient(app)


OWNER = {"Tailscale-User-Login": "team@crooksldn.com", "X-Forwarded-For": "100.64.0.9"}


def test_every_screen_route_is_the_owners_alone(s):
    client = app_with(s)
    screen = s.register("Office screen")
    for method, path, body in (
        ("get", "/displays", None),
        ("post", "/displays/register", {"name": "Kitchen"}),
        ("get", f"/displays/{screen['id']}", None),
        ("post", f"/displays/{screen['id']}/done", {"version": 0, "items_seen": 0}),
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
    first = client.get(f"/displays/{made['id']}?v=-1", headers=mine)
    assert first.status_code == 200 and first.json()["version"] == 0 and first.json()["showing"] is None
    assert client.get(f"/displays/{made['id']}?v=0", headers=mine).status_code == 204, "nothing new, nothing sent"
    # The owner's other device, knowing the id and the name but not the key, is not the screen.
    for headers in (OWNER, {**OWNER, "X-Screen-Key": "guess"}):
        refused = client.get(f"/displays/{made['id']}?v=-1", headers=headers)
        assert refused.status_code == 403 and refused.json()["code"] == "not_this_screen"
    taken = client.post("/displays/register", json={"name": "packing SCREEN"}, headers=OWNER)
    assert taken.status_code == 409 and "on right now" in taken.json()["detail"]
    s.show(made["id"], views.list_view("Today", ["One"]))
    now = client.get(f"/displays/{made['id']}?v=0", headers=mine).json()
    assert now["version"] == 1 and now["showing"]["title"] == "Today"
    stale = client.post(f"/displays/{made['id']}/done", json={"version": 0, "items_seen": 1}, headers=mine)
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    keyless = client.post(f"/displays/{made['id']}/done", json={"version": 1, "items_seen": 1}, headers=OWNER)
    assert keyless.status_code == 403 and keyless.json()["code"] == "not_this_screen"
    done = client.post(f"/displays/{made['id']}/done", json={"version": 1, "items_seen": 1}, headers=mine).json()
    assert done["version"] == 2 and done["showing"]["done_at"] and done["last_done"]["title"] == "Today"
    assert s.done()[0]["by"] == "team@crooksldn.com"
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
        runtime.settings = runtime.settings.model_copy(update={"tailscale_verify": False, "allowed_logins": "team@crooksldn.com"})
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


# --------------------------------------------------------------------------- round 6


def test_a_packed_slip_keeps_nothing_about_the_customer(tmp_path):
    """Round 6, B-03: done set done_at and kept the whole slip, name, address, phone and note,
    for good. Done cuts the slip down to what the done record needs, on disk as in memory."""
    path = tmp_path / "displays.json"
    s = DisplayStore(path)
    screen = s.register("Packing screen")
    key = screen["screen_key"]
    s.show(screen["id"], views.order_view(ORDER))
    assert "Sam Carter" in path.read_text(), "while it is up, the slip is the slip"
    s.mark_done(screen["id"], 1, screen_key=key, items_seen=len(views.order_view(ORDER)["order"]["items"]))
    kept = path.read_text()
    for gone in ("Sam Carter", "07700", "E8 1AA", "Sample Road", "gift", "HW-TEE"):
        assert gone not in kept, gone
    showing = s.poll(screen["id"], key)["showing"]
    assert set(showing) == {"kind", "ref", "title", "at", "by", "done_at"}
    assert showing["title"] == "Order #1047" and showing["ref"] == ORDER["order_id"]


def test_an_order_is_marked_packed_only_once_every_item_was_on_the_screen(s):
    """Round 6, B-04: the screen showed 6 or 12 items and "+N more", with Mark packed live."""
    screen = s.register("Packing screen")
    key = screen["screen_key"]
    many = dict(ORDER, items=[dict(ORDER["items"][1], title=f"Tee {i}", sku=f"SKU-{i}") for i in range(20)])
    slip = views.order_view(many)
    s.show(screen["id"], slip)
    n = len(slip["order"]["items"])
    assert n > 12
    for seen in (None, 0, 12, n - 1):
        with pytest.raises(DisplayError, match="Not every item on the order was on the screen"):
            s.mark_done(screen["id"], 1, screen_key=key, items_seen=seen)
    assert s.done() == []
    s.mark_done(screen["id"], 1, screen_key=key, items_seen=n)
    assert len(s.done()) == 1
    src = (Path(__file__).resolve().parent.parent / "web" / "display.js").read_text()
    assert "+ ' more on the order" not in src and "Ask CLIVE for the rest" not in src
    assert "items_seen" in src and "packedLocked()" in src and "'Next items'" in src and "'Next page'" in src
    assert "X-Screen-Key" in src


def test_whatever_is_left_up_comes_down_by_itself(tmp_path):
    clock = Clock()
    s = DisplayStore(tmp_path / "displays.json", clock=clock)
    screen = s.register("Office screen")
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
    screen = s.register("Packing screen")
    key = screen["screen_key"]
    many = dict(ORDER, items=[dict(ORDER["items"][1], title=f"Tee {i}", sku=f"SKU-{i}") for i in range(views.MAX_ITEMS + 15)])
    slip = views.order_view(many)
    o = slip["order"]
    assert o["partial"] is True and o["total_items"] == views.MAX_ITEMS + 15 and len(o["items"]) == views.MAX_ITEMS
    assert "partial" not in views.order_view(ORDER)["order"]
    s.show(screen["id"], slip)
    for seen in (views.MAX_ITEMS, views.MAX_ITEMS + 15, 10_000):
        with pytest.raises(DisplayError, match="more items than a screen shows"):
            s.mark_done(screen["id"], 1, screen_key=key, items_seen=seen)
    assert s.done() == [] and s.poll(screen["id"], key)["showing"].get("done_at") is None
    src = (WEB / "display.js").read_text(encoding="utf-8")
    assert "const partial = !!o.partial && !packed;" in src and "noteFoot(" in src


def test_every_field_of_a_view_is_bounded_and_the_record_stays_small(tmp_path):
    """Round 6, B-03: address lines, ids, times, image addresses and the whole view were
    unbounded. A hostile order, objective and list are cut to size before they are kept, a view
    past MAX_VIEW_BYTES is refused, and a full record — every screen at its largest, the done
    record full — stays under MAX_FILE_BYTES."""
    import json

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
        s.show(s.register("Office screen")["id"], {"kind": "list", "title": "T", "list": {"lines": ["y" * 200_000]}})
    for i in range(MAX_SCREENS):
        made = s.register(f"Screen {i}") if i else s.find("office screen")
        s.show(made["id"], order)
    s._data["done"] = [{"at": "2999-01-01T00:00:00+00:00", "screen": "S" * 40, "screen_id": "scr_000000000000",
                        "kind": "order", "ref": "r" * 200, "title": "t" * 120, "by": "b" * 80}] * MAX_DONE
    s._save()
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
    screen = s.register("Packing screen")
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
    s._save()
    fresh = store_module.install(path, clock=lambda: clock.now + SHOWING_KEEP_S + 60)   # the start: read and swept at once
    kept = path.read_text()
    assert "Sam Carter" not in kept and "Order #1" not in kept and "Order #2" in kept
    assert [d["ref"] for d in fresh.done()] == ["gid://shopify/Order/2"]


def _tool_session():
    from app.objectives import tools as objective_tools  # noqa: F401  registers the tools
    from app.session.models import Session
    from app.tools import display_tools  # noqa: F401

    return Session(session_id="screens-b05")


def test_an_objective_goes_up_only_once_this_conversation_was_shown_it(s, tmp_path):
    """Round 6, B-05, through the real dispatcher: objective_id had no issued-id rule, so any
    objective could be put on any screen. Now it is refused until the conversation has been
    shown it (objective_list here), like an order."""
    from app.objectives import store as objectives_store
    from app.tools.dispatch import dispatch

    objectives = objectives_store.install(tmp_path / "objectives-store")
    obj = objectives.create(title="Get the drop live", request="Get the SS26 drop live by Friday")
    screen = s.register("Office screen")
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
    office = s.register("Office screen")
    s.register("Office mac")
    for near in ("office", "screen", "offic screen", "Office screen please"):
        with pytest.raises(ToolError, match="Say its full name: Office mac, Office screen"):
            run(display_tools.screen_show(screen=near, order_id="gid://shopify/Order/1047"))
    assert all(x["showing"] is None for x in s.screens())
    out = run(display_tools.screen_show(screen="  OFFICE   screen ", order_id="gid://shopify/Order/1047"))
    assert out["screen"] == "Office screen" and s._data["screens"][office["id"]]["showing"]["kind"] == "order"


def test_a_list_is_refused_before_anything_is_done_with_it(s, monkeypatch):
    """Round 6, B-05: `lines` had no bounds and was walked whole before 40 were kept. The schema
    now says so, and the tool refuses before it looks for a screen or reads a line."""
    from app.tools import display_tools
    from app.tools.dispatch import dispatch
    from app.tools.registry import get

    schema = get("screen_show").input_schema["properties"]["lines"]
    assert schema["maxItems"] == views.MAX_LINES and schema["items"]["maxLength"] == views.MAX_LINE
    s.register("Office screen")

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
