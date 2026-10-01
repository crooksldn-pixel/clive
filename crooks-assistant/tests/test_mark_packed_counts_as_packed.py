"""A TV's Mark packed counts as packed (the owner's ruling 12, 1 October, closing B-04: "yes, the
mark packed should be in clive memory, not shopify").

- A row marked with a screen's own button, from the owner's remote, or with the remote's controls
  on a device that is itself a screen is said as packed (a list: done), on which screen and how,
  with nothing saying it may not count; the last is still never said to be the owner's remote.
- screen_list finds an order's packed record by its number as the owner says it ("1047",
  "#1047"), matched against the order row's title, as well as by its Shopify order id.
- An order asked about with no packed record is said to have none within what CLIVE keeps, in
  words built from DONE_KEEP_S and MAX_DONE.
- None of it reads or writes Shopify: the record is CLIVE's own (displays.json).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.displays import store as store_module
from app.displays import views
from app.displays.store import DisplayStore
from tests.test_displays import (
    ORDER,
    OWNER,
    OWNER_LOGIN,
    Tick,
    ack_all,
    app_with,
    handed_key,
    pair,
    run,
)

TV = "100.64.0.42"
TV_DEVICE = {"Tailscale-User-Login": OWNER_LOGIN, "X-Forwarded-For": TV}
# An order whose Shopify id is not its number, and two more.
BY_SCREEN = dict(ORDER, order_id="gid://shopify/Order/5550001", order_number="#1047")
BY_REMOTE = dict(ORDER, order_id="gid://shopify/Order/5550002", order_number="#1048")
BY_SCREEN_REMOTE = dict(ORDER, order_id="gid://shopify/Order/5550003", order_number="#1049")
# Words that would say a packed row may not count.
HEDGES = ("not a check", "word", "may not", "not count", "unverified", "unconfirmed", "not proven", "ruling", "whether")


class NoShopify:
    """A Shopify client, and the order reader built on one, that fail the test on any use."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        self.calls.append(name)
        pytest.fail(f"Shopify was reached ({name}) while an order was marked packed or read back")

    def method(self, name: str):
        def called(*_args, **_kwargs):
            self.calls.append(name)
            pytest.fail(f"Shopify was reached ({name}) while an order was marked packed or read back")

        return called


@pytest.fixture
def no_shopify(monkeypatch):
    from app.clients.shopify import ShopifyClient
    from app.tools import shopify_tools

    trip = NoShopify()
    monkeypatch.setattr(shopify_tools, "_client", trip)
    monkeypatch.setattr(shopify_tools, "_hydrator", trip)
    for name in ("graphql", "mutate", "shop", "access_scopes", "health"):
        monkeypatch.setattr(ShopifyClient, name, trip.method(name))
    yield trip
    assert trip.calls == []


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives" / "displays.json", mono=Tick())


def _tv(s, client):
    """A TV named at /display from its own tailnet address and approved: its id, key and headers."""
    made = client.post("/displays/register", json={"name": "Packing TV"}, headers=TV_DEVICE)
    sid, key = made.json()["id"], handed_key(made)
    s.approve("Packing TV", made.json()["code"])
    tv = {**TV_DEVICE, "Cookie": f"clive_screen={key}"}
    assert client.get(f"/displays/{sid}?v=-1", headers=tv).status_code == 200
    return sid, key, tv


def _by_screen(s, client, sid, key, tv, view):
    """The TV's own Mark packed: every page shown, then the tap."""
    s.show(sid, view)
    v = s.remote(sid)["panes"][0]["v"]
    ack_all(s, sid, key, version=v)
    done = client.post(f"/displays/{sid}/done", json={"version": v, "confirm": True}, headers=tv)
    assert done.status_code == 200, done.text


def _by_remote(s, client, sid, view, headers):
    """Every item ticked and the pane marked done through the remote's routes, from `headers`."""
    s.show(sid, view)
    pane = client.get(f"/displays/{sid}/remote", headers=OWNER).json()["panes"][0]
    for item in pane.get("items", pane.get("lines", [])):
        if not item.get("sent"):
            ticked = client.post(f"/displays/{sid}/remote/tick", headers=headers,
                                 json={"pane": 0, "item": item["i"], "packed": True, "version": pane["v"]})
            assert ticked.status_code == 200, ticked.text
    done = client.post(f"/displays/{sid}/remote/done", json={"pane": 0, "version": pane["v"]}, headers=headers)
    assert done.status_code == 200, done.text


def test_each_way_of_marking_an_order_packed_is_said_as_packed_on_its_screen(s, no_shopify):
    from app.tools import display_tools

    client = app_with(s)
    sid, key, tv = _tv(s, client)
    _by_screen(s, client, sid, key, tv, views.order_view(BY_SCREEN))
    _by_remote(s, client, sid, views.order_view(BY_REMOTE), OWNER)
    _by_remote(s, client, sid, views.order_view(BY_SCREEN_REMOTE), tv)
    said = {
        BY_SCREEN["order_id"]: ("screen", "packed on the Packing TV: marked with that screen's own button"),
        BY_REMOTE["order_id"]: ("remote", "packed on the Packing TV: marked from the owner's remote, with every item ticked"),
        BY_SCREEN_REMOTE["order_id"]: ("screen_remote", "packed on the Packing TV: marked with the remote's controls on a "
                                                        "device that is itself one of the screens, not the owner's own remote"),
    }
    for order_id, (how, words) in said.items():
        listed = run(display_tools.screen_list(order_id=order_id))
        assert [row["ref"] for row in listed["done"]] == [order_id]
        row = listed["done"][0]
        assert row["how"] == how and row["screen"] == "Packing TV" and row["kind"] == "order"
        assert row["marked"] == words
        for hedge in HEDGES:
            assert hedge not in row["marked"], (how, hedge)
        assert "packed_record" not in listed
    tv_row = run(display_tools.screen_list(order_id=BY_SCREEN_REMOTE["order_id"]))["done"][0]["marked"]
    assert "from the owner's remote" not in tv_row and "not the owner's own remote" in tv_row
    # A list: done, not packed, whichever way it was marked.
    _by_remote(s, client, sid, views.list_view("Today", ["One", "Two"]), OWNER)
    listed = run(display_tools.screen_list())["done"][0]
    assert listed["kind"] == "list" and listed["marked"] == "done on the Packing TV: marked from the owner's remote, with every item ticked"
    _by_screen(s, client, sid, key, tv, views.list_view("Tomorrow", ["Three"]))
    listed = run(display_tools.screen_list())["done"][0]
    assert listed["kind"] == "list" and listed["marked"] == "done on the Packing TV: marked with that screen's own button"
    _by_remote(s, client, sid, views.list_view("Later", ["Four"]), tv)
    listed = run(display_tools.screen_list())["done"][0]
    assert listed["how"] == "screen_remote" and listed["marked"].startswith("done on the Packing TV: ")
    assert "packed" not in listed["marked"]
    # CLIVE's own record, on its own disk, and Shopify never reached.
    kept = s.path.read_text(encoding="utf-8")
    for order in (BY_SCREEN, BY_REMOTE, BY_SCREEN_REMOTE):
        assert order["order_id"] in kept
    assert no_shopify.calls == []


def test_an_order_is_found_by_its_number_as_the_owner_says_it(s, no_shopify):
    from app.tools import display_tools

    client = app_with(s)
    sid, key, tv = _tv(s, client)
    _by_screen(s, client, sid, key, tv, views.order_view(BY_SCREEN))
    # Another order whose Shopify id carries 1047 but whose number is 2050, and a list.
    other = dict(ORDER, order_id="gid://shopify/Order/1047", order_number="#2050")
    _by_remote(s, client, sid, views.order_view(other), OWNER)
    _by_remote(s, client, sid, views.list_view("Today", ["One"]), OWNER)
    by_id = run(display_tools.screen_list(order_id=BY_SCREEN["order_id"]))["done"]
    assert [(row["ref"], row["title"]) for row in by_id] == [(BY_SCREEN["order_id"], "Order #1047")]
    assert run(display_tools.screen_list(order_id="1047"))["done"] == by_id
    assert run(display_tools.screen_list(order_id="#1047"))["done"] == by_id
    assert [row["ref"] for row in run(display_tools.screen_list(order_id="2050"))["done"]] == [other["order_id"]]
    for number in ("2099", "#2099", "5550001"):
        out = run(display_tools.screen_list(order_id=number))
        assert out["done"] == [] and "packed_record" in out, number
    # A list's or an objective's row is never an order's, whatever its title says.
    for kind, ref in (("list", ""), ("objective", "obj_0123abcd")):
        s._data["done"].append({"kind": kind, "ref": ref, "title": "Order #1047", "at": "2999-01-01T00:00:00+00:00",
                                "screen": "Packing TV", "screen_id": sid, "by": OWNER_LOGIN, "how": "remote"})
    assert run(display_tools.screen_list(order_id="1047"))["done"] == by_id
    assert run(display_tools.screen_list(order_id="#1047"))["done"] == by_id
    assert no_shopify.calls == []


def test_an_order_with_no_packed_record_is_said_to_have_none_within_what_clive_keeps(s, no_shopify, monkeypatch):
    from app.tools import display_tools

    # `note` as before: no screens yet, and the new field beside it.
    out = run(display_tools.screen_list(order_id="1047"))
    assert out["note"] == "No screens yet: open CLIVE's address with /display on a screen and give it a name."
    words = out["packed_record"]
    days, kept = store_module.DONE_KEEP_S // 86_400, store_module.MAX_DONE
    assert words == (f"CLIVE has no packed record for order #1047 in what it keeps: packed and done rows from the last "
                     f"{days} days, at most {kept} of them.")
    assert "was not packed" not in words and "not been packed" not in words
    pair(s, "Office screen")
    out = run(display_tools.screen_list(order_id="#1047"))
    assert "note" not in out and out["packed_record"] == words
    s.register("Kitchen screen")
    out = run(display_tools.screen_list(order_id=BY_SCREEN["order_id"]))
    assert out["note"] == "A pending screen shows a six-digit code: it takes nothing until the owner reads the code out."
    assert out["packed_record"].startswith("CLIVE has no packed record for that order in what it keeps")
    # Built from what is kept, not written in.
    monkeypatch.setattr(store_module, "DONE_KEEP_S", 30 * 86_400)
    monkeypatch.setattr(store_module, "MAX_DONE", 77)
    words = run(display_tools.screen_list(order_id="1047"))["packed_record"]
    assert "the last 30 days, at most 77 of them" in words and f"{days} days" not in words
    # Not asked about an order: no such field.
    assert "packed_record" not in run(display_tools.screen_list())
    assert no_shopify.calls == []


def test_what_is_kept_and_how_a_row_is_marked_are_unchanged():
    assert store_module.DONE_HOW == ("screen", "remote", "screen_remote")
    assert store_module.DONE_KEEP_S == 90 * 86_400 and store_module.MAX_DONE == 500
    assert store_module.MAX_FILE_BYTES == 4_000_000
    row = DisplayStore._done_row({"kind": "order", "ref": BY_SCREEN["order_id"], "title": "Order #1047", "how": "screen"})
    assert set(row) == {"kind", "ref", "title", "at", "screen", "screen_id", "by", "how"}
    assert DisplayStore._done_row({**row, "how": "a test's word"})["how"] is None


def test_nothing_changed_here_still_calls_the_ruling_one_to_be_made():
    root = Path(__file__).resolve().parents[1]
    for name in ("app/displays/store.py", "app/tools/display_tools.py", "tests/test_screens_r10.py",
                 "tests/test_r11_screens_server.py"):
        text = (root / name).read_text(encoding="utf-8")
        for stale in ("still to be made", "the owner's ruling, not this code's", "not a check", "no ruling in round 10"):
            assert stale not in text, (name, stale)
