"""A screen's key is a cookie its page's script cannot read (the round-9 deploy review, B2-01,
the server's half).

The screen page kept the full key in localStorage, where anyone with the TV's browser, or an
extension on it, could copy it and ask for future slips. Now:

- POST /displays/register sets the key as `clive_screen` — HttpOnly, Secure, SameSite=Strict,
  for /displays only, kept 400 days — and its answer no longer carries it.
- Every screen request (the ask, /seen, /done, /video) is known by that cookie and nothing
  else; X-Screen-Key is not read on them.
- A screen paired before this names itself once more, sending the key it kept as X-Screen-Key
  to /register — the one place that header is read — and is handed the cookie with a new key.
  It stays approved, and the old key is spent.
- The owner removing a screen and naming a new device ("Remove the old screen and use this
  one") works as it did.

A browser keeps a Secure cookie only over https, so every client here is https, as the tailnet
serves the app.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.displays import store as store_module
from app.displays import views
from tests import fake_credentials
from tests.test_displays import ORDER, OWNER, Tick, ack_all, handed_key, later

COOKIE = re.compile(r"^clive_screen=([A-Za-z0-9_-]{24,}); HttpOnly; Secure; SameSite=Strict; Path=/displays; Max-Age=34560000$")


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives" / "displays.json", mono=Tick())


def browser(s) -> TestClient:
    """A device's browser: the screens' routes over https, keeping the cookies it is given as a
    browser does (by its path, and only over https when they say Secure)."""
    from types import SimpleNamespace

    from app.routes import displays

    app = FastAPI()
    app.include_router(displays.router)
    app.state.runtime = SimpleNamespace(allowed_logins=("owner@example.com",),
                                        settings=SimpleNamespace(writes_local_owner=False, tailscale_verify=False, tailscale_cli=""))
    return TestClient(app, base_url="https://testserver", headers=OWNER)


def test_naming_a_screen_hands_it_the_key_as_a_cookie_and_never_in_the_answer(s):
    tv = browser(s)
    answer = tv.post("/displays/register", json={"name": "Packing screen"})
    assert answer.status_code == 200 and answer.headers["cache-control"] == "no-store"
    cookie = answer.headers["set-cookie"]
    found = COOKIE.fullmatch(cookie)
    assert found, cookie
    key = found.group(1)
    made = answer.json()
    assert set(made) == {"id", "name", "pending", "code", "code_expires_in"} and made["pending"] is True
    assert key not in answer.text, "never in what the page's script reads"
    assert "key" not in json.dumps(made).lower()
    # The browser sends it back on the screen's own routes, by itself: no header carries it.
    asked = tv.get(f"/displays/{made['id']}")
    assert asked.status_code == 200 and asked.json()["pending"] is True
    assert asked.request.headers["cookie"] == f"clive_screen={key}"
    assert "x-screen-key" not in asked.request.headers
    # And only there: the path keeps it off everything else the app serves.
    elsewhere = tv.get("/objectives")
    assert "cookie" not in elsewhere.request.headers
    # A Secure cookie never goes over plain http.
    plain = tv.get(f"http://testserver/displays/{made['id']}")
    assert "cookie" not in plain.request.headers and plain.status_code == 403
    # Approved with the code it shows, it is shown things: the cookie is the screen.
    assert s.approve("Packing screen", made["code"])["approved"] is True
    s.show(made["id"], views.list_view("Today", ["One"]))
    assert tv.get(f"/displays/{made['id']}?v=-1").json()["showing"]["title"] == "Today"
    assert tv.get(f"/displays/{made['id']}?v=1").status_code == 204


def test_every_screen_request_is_known_by_its_cookie_and_never_by_the_old_header(s):
    tv = browser(s)
    made = tv.post("/displays/register", json={"name": "Packing screen"})
    key, sid = handed_key(made), made.json()["id"]
    s.approve("Packing screen", made.json()["code"])
    s.show(sid, views.list_view("Today", ["One"]))
    s.show(sid, views.video_view("dQw4w9WgXcQ", title="Heat"), beside=True)
    other = TestClient(tv.app, base_url="https://testserver", headers=OWNER)        # the key, but no cookie
    said = {"pane": 1, "version": 2, "state": "playing", "at": 1.0}
    requests = (("get", f"/displays/{sid}?v=-1", None), ("post", f"/displays/{sid}/seen", {"version": 1, "start": 0, "end": 1}),
                ("post", f"/displays/{sid}/done", {"version": 1, "confirm": True}), ("post", f"/displays/{sid}/video", said))
    for method, path, body in requests:
        kwargs = {"json": body} if body is not None else {}
        refused = getattr(other, method)(path, headers={"X-Screen-Key": key}, **kwargs)
        assert refused.status_code == 403 and refused.json()["code"] == "not_this_screen", path
    assert s.done() == [] and s.page_plan(sid, 1) is None, "nothing the header asked for was done"
    # The same requests with the cookie are the screen's own.
    assert tv.get(f"/displays/{sid}?v=-1").json()["beside"]["kind"] == "video"
    assert tv.post(f"/displays/{sid}/seen", json={"version": 1, "start": 0, "end": 1}).json()["seen"] == 1
    later(s)
    assert tv.post(f"/displays/{sid}/done", json={"version": 1, "confirm": True}).json()["showing"]["done_at"]
    assert tv.post(f"/displays/{sid}/video", json=said).json() == {"heard": True}
    # A cookie with another key is not the screen either.
    other.cookies.set("clive_screen", "not-its-key", domain="testserver", path="/displays")
    assert other.get(f"/displays/{sid}?v=-1").status_code == 403


def _paired_before(path, *, marked: bool) -> tuple[str, str]:
    """A screen written down before the key became a cookie, showing a customer's slip; its page
    kept the key in its own storage. `marked` False is a record from before approval existed
    (no `paired` at all), which counts as approved."""
    key = fake_credentials.body("a screen key kept in a page's own storage", 32)   # never a literal (rule B)
    screen = {"id": "scr_0123456789ab", "name": "Office screen", "key": "office screen", "secret": store_module._key_hash(key),
              "created_at": "2026-09-27T10:00:00+00:00", "last_seen": "2026-09-27T10:00:00+00:00", "version": 4,
              "showing": {**views.order_view(ORDER), "at": store_module._now_iso(), "by": "clive", "v": 4}, "beside": None}
    if marked:
        screen["paired"] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"screens": {screen["id"]: screen}, "done": []}), encoding="utf-8")
    return screen["id"], key


@pytest.mark.parametrize("marked", [True, False])
def test_a_screen_paired_before_the_cookie_moves_over_once_and_stays_approved(tmp_path, marked):
    path = tmp_path / "objectives" / "displays.json"
    sid, old = _paired_before(path, marked=marked)
    s = store_module.install(path, mono=Tick())
    tv = browser(s)
    # Its old page, still sending the key as a header, is not the screen on its routes.
    assert tv.get(f"/displays/{sid}?v=-1", headers={"X-Screen-Key": old}).status_code == 403
    # The new page names itself once more with the key it kept: /register reads the header, for
    # exactly this, and hands the cookie.
    moved = tv.post("/displays/register", json={"name": "Office screen"}, headers={"X-Screen-Key": old})
    assert moved.status_code == 200
    new = handed_key(moved)
    assert COOKIE.fullmatch(moved.headers["set-cookie"]) and new != old
    assert moved.json() == {"id": sid, "name": "Office screen", "pending": False}, "the same screen, still approved"
    assert s._data["screens"][sid].get("paired", True) is True and "pairing" not in s._data["screens"][sid]
    shown = tv.get(f"/displays/{sid}?v=-1").json()
    assert shown["pending"] is False and shown["showing"]["title"] == "Order #1047", "still showing what it showed"
    # The old key is spent: not the screen, and it cannot name itself again with it.
    stranger = TestClient(tv.app, base_url="https://testserver", headers=OWNER)
    assert stranger.get(f"/displays/{sid}?v=-1", headers={"X-Screen-Key": old}).status_code == 403
    again = stranger.post("/displays/register", json={"name": "Office screen"}, headers={"X-Screen-Key": old})
    assert again.status_code == 409 and again.json()["code"] == "name_taken" and "set-cookie" not in again.headers
    assert old not in path.read_text() and new not in path.read_text(), "only hashes are kept"


def test_a_wrong_or_borrowed_old_key_is_no_way_in(s):
    tv = browser(s)
    first = tv.post("/displays/register", json={"name": "Office screen"})
    s.approve("Office screen", first.json()["code"])
    other = browser(s)
    second = other.post("/displays/register", json={"name": "Packing screen"})
    s.approve("Packing screen", second.json()["code"])
    stranger = TestClient(tv.app, base_url="https://testserver", headers=OWNER)
    for key in ("guess", handed_key(second)):              # nonsense, and another screen's key
        refused = stranger.post("/displays/register", json={"name": "Office screen"}, headers={"X-Screen-Key": key})
        assert refused.status_code == 409 and refused.json()["code"] == "name_taken"
        assert "set-cookie" not in refused.headers
    assert tv.get(f"/displays/{first.json()['id']}?v=-1").status_code == 200, "the screen keeps its cookie"


def test_a_screen_waiting_for_approval_renews_its_code_with_its_cookie(s):
    """The page asks for a new code when its old one runs out (web/display.js renewCode): with
    its cookie now, and it is handed a new one."""
    tv = browser(s)
    made = tv.post("/displays/register", json={"name": "Packing screen"})
    renewed = tv.post("/displays/register", json={"name": "Packing screen"})
    assert renewed.status_code == 200 and renewed.json()["id"] == made.json()["id"] and renewed.json()["pending"] is True
    assert re.fullmatch(r"\d{6}", renewed.json()["code"]) and handed_key(renewed) != handed_key(made)
    assert tv.get(f"/displays/{made.json()['id']}").json()["pending"] is True
    assert s.approve("Packing screen", renewed.json()["code"])["approved"] is True
    assert tv.get(f"/displays/{made.json()['id']}").json()["pending"] is False


def test_the_owner_removes_the_old_screen_and_a_new_device_takes_its_name(s):
    """"Remove the old screen and use this one": the owner's forget, then the new device names
    itself and is handed its own cookie; the old device's cookie is nothing now."""
    old_tv = browser(s)
    first = old_tv.post("/displays/register", json={"name": "Packing screen"})
    s.approve("Packing screen", first.json()["code"])
    s.show(first.json()["id"], views.order_view(ORDER))
    new_tv = browser(s)
    taken = new_tv.post("/displays/register", json={"name": "Packing screen"})
    assert taken.status_code == 409 and taken.json()["code"] == "name_taken" and "set-cookie" not in taken.headers
    assert new_tv.post("/displays/forget", json={"name": "Packing screen"}).json() == {"forgotten": "Packing screen"}
    fresh = new_tv.post("/displays/register", json={"name": "Packing screen"})
    assert fresh.status_code == 200 and fresh.json()["id"] != first.json()["id"] and fresh.json()["pending"] is True
    assert COOKIE.fullmatch(fresh.headers["set-cookie"])
    assert new_tv.get(f"/displays/{fresh.json()['id']}").json()["showing"] is None, "a new screen, with nothing on it"
    assert old_tv.get(f"/displays/{first.json()['id']}").status_code == 404
    assert "Sam Carter" not in s.path.read_text()


def test_the_screens_done_answer_is_its_own_record_by_its_cookie(tmp_path):
    """/done answers with what the screen shows now, read with the same cookie it came with."""
    s = store_module.install(tmp_path / "displays.json", mono=Tick())
    tv = browser(s)
    made = tv.post("/displays/register", json={"name": "Packing screen"})
    sid = made.json()["id"]
    s.approve("Packing screen", made.json()["code"])
    s.show(sid, views.order_view(ORDER))
    ack_all(s, sid, handed_key(made))
    done = tv.post(f"/displays/{sid}/done", json={"version": 1, "confirm": True})
    assert done.status_code == 200 and done.json()["showing"]["done_at"] and "order" not in done.json()["showing"]
