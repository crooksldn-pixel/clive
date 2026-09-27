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
from app.displays.store import MAX_DONE, MAX_SCREENS, DisplayError, DisplayStore
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


def test_a_name_is_one_screen_however_it_is_typed(s):
    first = s.register("Office screen")
    again = s.register("  office   SCREEN! ")
    assert again["id"] == first["id"] and again["name"] == "Office screen"
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
    assert s.poll(screen["id"])["version"] == 0
    s.show(screen["id"], views.list_view("Today", ["One", "Two"]))
    shown = s.poll(screen["id"])
    assert shown["version"] == 1 and shown["showing"]["title"] == "Today" and shown["showing"]["at"]
    # A tap on what the screen drew before the change is refused, and nothing is recorded.
    with pytest.raises(DisplayError, match="changed before that tap"):
        s.mark_done(screen["id"], 0, by="team@crooksldn.com")
    assert s.done() == []
    s.mark_done(screen["id"], 1, by="team@crooksldn.com")
    after = s.poll(screen["id"])
    assert after["version"] == 2 and after["showing"]["done_at"]
    assert after["last_done"]["title"] == "Today"
    # A second tap on the same thing is the same record, not another.
    s.mark_done(screen["id"], 2)
    assert len(s.done()) == 1 and s.done()[0]["by"] == "team@crooksldn.com"
    # Clearing empties it.
    s.show(screen["id"], None)
    assert s.poll(screen["id"])["showing"] is None


def test_the_done_record_is_per_screen_and_bounded(s):
    a = s.register("Office screen")
    b = s.register("Packing screen")
    s.show(a["id"], {"kind": "order", "ref": "gid://shopify/Order/1", "title": "Order 1001"})
    s.mark_done(a["id"], 1)
    assert s.poll(b["id"])["last_done"] is None, "done on one screen is not done on another"
    assert s.done(ref="gid://shopify/Order/1")[0]["screen"] == "Office screen"
    for i in range(MAX_DONE + 5):
        s.show(b["id"], {"kind": "list", "ref": "", "title": f"List {i}"})
        s.mark_done(b["id"], s.poll(b["id"])["version"])
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
    assert again.poll(screen["id"])["showing"]["title"] == "Today"
    path.write_text("{not json", encoding="utf-8")
    assert DisplayStore(path).screens() == [], "an unreadable record starts afresh rather than failing"


def test_only_a_real_screen_id_is_looked_up(s):
    s.register("Office screen")
    assert s.get("../../etc/passwd") is None and s.get("scr_zzzzzzzzzzzz") is None
    assert s.poll("scr_000000000000") is None


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
    out = run(display_tools.screen_show(screen="office", order_id="gid://shopify/Order/1047"))
    assert out["screen"] == "Office screen" and out["showing"] == "Order #1047"
    assert fake.asked == ["gid://shopify/Order/1047"]
    assert out["on"] is False and "next on" in out["note"]
    showing = s.poll(s.find("office")["id"])["showing"]
    assert showing["kind"] == "order" and showing["order"]["customer"] == "Sam Carter" and showing["by"] == "clive"


def test_screen_show_takes_one_thing_and_names_the_screens_it_knows(s):
    from app.tools import display_tools

    s.register("Office screen")
    with pytest.raises(ToolError, match="Say one thing to show"):
        run(display_tools.screen_show(screen="office screen"))
    with pytest.raises(ToolError, match="Say one thing to show"):
        run(display_tools.screen_show(screen="office screen", title="T", lines=["a"], clear=True))
    with pytest.raises(ToolError, match="The screens are: Office screen"):
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
    showing = s.poll(s.find("office")["id"])["showing"]
    assert showing["objective"]["next"] == ["Resize the lookbook images"]
    with pytest.raises(ToolError, match="There is no objective"):
        run(display_tools.screen_show(screen="office screen", objective_id="obj_00000000"))


def test_screen_list_says_what_is_up_and_what_was_packed(s):
    from app.tools import display_tools

    empty = run(display_tools.screen_list())
    assert empty["screens"] == [] and "/display" in empty["note"]
    screen = s.register("Packing screen")
    s.show(screen["id"], {"kind": "order", "ref": "gid://shopify/Order/1047", "title": "Order #1047"})
    s.poll(screen["id"])   # the screen asked: it is on
    s.mark_done(screen["id"], 1, by="team@crooksldn.com")
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
        ("post", f"/displays/{screen['id']}/done", {"version": 0}),
    ):
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, **kwargs).status_code == 403, f"{path} from the server itself"
        stranger = {**OWNER, "Tailscale-User-Login": "someone@example.com"}
        assert getattr(client, method)(path, headers=stranger, **kwargs).status_code == 403, f"{path} from a stranger"
    assert client.get("/displays", headers=OWNER).status_code == 200
    assert app_with(s, local_owner=True).get("/displays").status_code == 200, "the owner said the server is him"


def test_a_screen_names_itself_asks_and_marks_done(s):
    client = app_with(s)
    made = client.post("/displays/register", json={"name": "Packing screen"}, headers=OWNER).json()
    assert made["name"] == "Packing screen" and made["id"].startswith("scr_")
    first = client.get(f"/displays/{made['id']}?v=-1", headers=OWNER)
    assert first.status_code == 200 and first.json()["version"] == 0 and first.json()["showing"] is None
    assert client.get(f"/displays/{made['id']}?v=0", headers=OWNER).status_code == 204, "nothing new, nothing sent"
    s.show(made["id"], views.list_view("Today", ["One"]))
    now = client.get(f"/displays/{made['id']}?v=0", headers=OWNER).json()
    assert now["version"] == 1 and now["showing"]["title"] == "Today"
    stale = client.post(f"/displays/{made['id']}/done", json={"version": 0}, headers=OWNER)
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    done = client.post(f"/displays/{made['id']}/done", json={"version": 1}, headers=OWNER).json()
    assert done["version"] == 2 and done["showing"]["done_at"] and done["last_done"]["title"] == "Today"
    assert s.done()[0]["by"] == "team@crooksldn.com"
    assert client.get("/displays/scr_000000000000", headers=OWNER).status_code == 404
    assert client.post("/displays/register", json={"name": "!!!"}, headers=OWNER).status_code == 400


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
    assert "setTimeout(finish, 20000)" in source
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
