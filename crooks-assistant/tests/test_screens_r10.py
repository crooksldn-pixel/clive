"""The owner's screens, the round-9 deploy review's findings on the server's side of them.

- B-REMOTE-OFF: the remote's whole-screen off names the screen's version it was tapped on, and
  a screen that has moved on since is left as it is (409 stale).
- B-03: a deletion whose purge journal is not durable, and whose record is not either, is not
  made and is not said to be.
- B-04: a screen's pages are held to the plan the server issues, and a screen's "done" is
  recorded, and said by CLIVE, as that screen's own word; the remote's as the owner's ticks.
- B-NEW-DONE-LOSS: every screen showing two of the largest views beside a full done record
  fits, and a change that would not is refused with nothing changed; no done row is ever
  dropped to make room.
"""

from __future__ import annotations

import json

import pytest

from app.displays import store as store_module
from app.displays import views
from app.displays.store import (
    MAX_DONE,
    MAX_SCREENS,
    DisplayStore,
    Full,
    NotDurable,
    NotSaved,
    Stale,
)
from app.tools.registry import ToolError
from tests.test_displays import (
    ORDER,
    OWNER,
    OWNER_LOGIN,
    Tick,
    _flaky_record_flush,
    ack_all,
    app_with,
    as_screen,
    later,
    pair,
    run,
)

CUSTOMER = ("Sam Carter", "E8 1AA", "Sample Road", "gift")


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives" / "displays.json", mono=Tick())


# --------------------------------------------------------------------------- B-REMOTE-OFF


def test_a_whole_screen_off_tapped_on_an_older_view_takes_nothing_down_that_went_up_since(s):
    """B-REMOTE-OFF (demonstrated): the remote's whole-screen off carried no version, and
    take_off checked one only for a single pane, so an off tapped on an older view deleted
    whatever was up when it arrived — a customer's slip put up in between included, for good.
    It now names the screen's version the remote was showing (its view's top-level `version`),
    checked under the store's lock before either pane comes down: a screen that has moved on is
    409 stale and nothing is taken off. Anything but a pane with its version, or the screen's
    version alone, is 422."""
    client = app_with(s)
    screen = pair(s, "Packing screen")
    sid = screen["id"]
    s.show(sid, views.list_view("Today", ["One"]))
    seen = client.get(f"/displays/{sid}/remote", headers=OWNER).json()        # the remote's view
    s.show(sid, views.order_view(ORDER), beside=True)                          # a slip goes up meanwhile
    tapped = client.post(f"/displays/{sid}/remote/off", json={"screen_version": seen["version"]}, headers=OWNER)
    assert tapped.status_code == 409 and tapped.json()["code"] == "stale"
    assert [p["kind"] for p in client.get(f"/displays/{sid}/remote", headers=OWNER).json()["panes"]] == ["list", "order"]
    assert "Sam Carter" in s.path.read_text(), "nothing was taken off"
    # A tick from another device moves the screen on too: an off tapped before it changes nothing.
    now = client.get(f"/displays/{sid}/remote", headers=OWNER).json()["version"]
    s.tick(sid, 0, 0, True, 1)
    stale = client.post(f"/displays/{sid}/remote/off", json={"screen_version": now}, headers=OWNER)
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    for body in ({}, {"pane": 0}, {"version": 1}, {"pane": 0, "version": 1, "screen_version": now + 1},
                 {"screen_version": str(now + 1)}, {"screen_version": True}, {"screen_version": -1},
                 {"screen_version": now + 1, "everything": True}):
        assert client.post(f"/displays/{sid}/remote/off", json=body, headers=OWNER).status_code == 422, body
    assert len(client.get(f"/displays/{sid}/remote", headers=OWNER).json()["panes"]) == 2
    # Tapped on the view as it is now: everything comes off, and off the disk.
    now = client.get(f"/displays/{sid}/remote", headers=OWNER).json()["version"]
    off = client.post(f"/displays/{sid}/remote/off", json={"screen_version": now}, headers=OWNER)
    assert off.status_code == 200 and off.json()["panes"] == []
    for word in CUSTOMER:
        assert word not in s.path.read_text(), word
    # In the store itself, the same rule under its lock.
    s.show(sid, views.order_view(ORDER))
    with pytest.raises(Stale):
        s.take_off(sid, screen_version=now)
    assert s.remote(sid)["panes"][0]["kind"] == "order"


def test_clives_own_turn_the_screen_off_takes_what_is_up_now_and_says_what(s):
    """B-REMOTE-OFF, CLIVE's half: "turn the screen off" is the owner's own request, made now,
    so it takes off whatever is up when it runs — and its answer names each thing that came
    off, so he hears exactly what went."""
    from app.tools import display_tools

    screen = pair(s, "Packing screen")
    s.show(screen["id"], views.list_view("Today", ["One"]))
    s.show(screen["id"], views.order_view(ORDER), beside=True)
    out = run(display_tools.screen_off(screen="Packing screen"))
    assert out == {"screen": "Packing screen", "taken_off": 2, "showing": "nothing", "took_off": ["Today", "Order #1047"]}
    assert "Sam Carter" not in s.path.read_text()


# --------------------------------------------------------------------------- B-03


def _journal_flush_fails(monkeypatch):
    """Only the purge journal's folder flush fails; the record's works."""
    real_flush = store_module._fsync_dir
    real_replace = store_module.os.replace
    placed: list[str] = []

    def replace(src, dst):
        placed.append(str(dst).rsplit("/", 1)[-1])
        real_replace(src, dst)

    def flush(folder):
        if placed and placed[-1].endswith(".purge.json"):
            raise OSError(5, "I/O error")
        real_flush(folder)

    monkeypatch.setattr(store_module.os, "replace", replace)
    monkeypatch.setattr(store_module, "_fsync_dir", flush)


def test_a_deletion_whose_journal_is_not_durable_and_whose_record_is_not_either_is_not_made(tmp_path, monkeypatch):
    """B-03 (round 9): _journal returned False when its folder flush failed and _commit went on
    as if it had not, so a slip cleared while the disk was failing was answered "done but not
    saved yet" and stood in memory with nothing durable behind it: after a power cut the old
    record came back with nothing owed against it, and so did the slip. Now a deletion stands
    only on a durable journal or a durable record. Here the journal's FIRST folder flush fails,
    and so does the record's: the clear is not made, the caller is told nothing was changed, and
    a restart from the old durable record agrees with what the caller was told."""
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    screen = pair(s, "Packing screen")
    key = screen["screen_key"]
    s.show(screen["id"], views.order_view(ORDER))
    durable = path.read_bytes()
    placed, restore = _flaky_record_flush(monkeypatch, fail_from=1)
    with pytest.raises(NotSaved, match="nothing was changed"):
        s.show(screen["id"], None)
    assert placed == ["displays.purge.json", "displays.json"], "both were put in place; neither was flushed"
    assert s.poll(screen["id"], key)["showing"]["title"] == "Order #1047", "not made: the slip is up, as said"
    assert not s.journal_path.exists(), "and the journal is put back as it was: nothing owed"
    restore()
    # The power goes: neither rename was on the disk.
    path.write_bytes(durable)
    s.journal_path.unlink(missing_ok=True)
    restarted = DisplayStore(path, mono=Tick())
    assert restarted.poll(screen["id"], key)["showing"]["title"] == "Order #1047", "what the caller was told"
    # The disk well again: the clear is made, and stays made.
    restarted.show(screen["id"], None)
    assert DisplayStore(path, mono=Tick()).poll(screen["id"], key)["showing"] is None
    for word in CUSTOMER:
        assert word not in path.read_text(), word


def test_a_packed_slip_refused_on_a_failing_disk_is_not_recorded_and_can_be_tapped_again(tmp_path, monkeypatch):
    """B-03 for "done": the slip's cut and its done row stand or fall together, and a tap that
    was refused leaves the pages the screen told, so tapping again once the disk is well is
    enough."""
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    screen = pair(s, "Packing screen")
    key = screen["screen_key"]
    s.show(screen["id"], views.order_view(ORDER))
    ack_all(s, screen["id"], key)
    _placed, restore = _flaky_record_flush(monkeypatch, fail_from=1)
    with pytest.raises(NotSaved):
        s.mark_done(screen["id"], 1, screen_key=key, confirmed=True)
    restore()
    assert s.done() == [] and s.poll(screen["id"], key)["showing"].get("done_at") is None
    s.mark_done(screen["id"], 1, screen_key=key, confirmed=True)
    assert [row["ref"] for row in s.done()] == [ORDER["order_id"]]
    assert "Sam Carter" not in path.read_text()


def test_a_deletion_whose_record_is_durable_stands_even_if_its_journal_was_not(tmp_path, monkeypatch):
    """B-03: the record itself durable is enough; the journal is then not needed at all."""
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    screen = pair(s, "Packing screen")
    s.show(screen["id"], views.order_view(ORDER))
    _journal_flush_fails(monkeypatch)
    s.show(screen["id"], None)
    assert not s.journal_path.exists() and not s.unsaved
    assert DisplayStore(path, mono=Tick()).poll(screen["id"], screen["screen_key"])["showing"] is None


def test_a_refused_deletion_leaves_an_earlier_owed_one_owed_and_adds_nothing(tmp_path, monkeypatch):
    """B-03 across two deletions: one made on a durable journal (its record not durable) is
    still owed after a second, refused on a failing disk, and the journal is put back to it —
    so a restart takes down the first and not the second, exactly as the two callers were told."""
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    gone = pair(s, "Office screen")
    kept = pair(s, "Packing screen")
    s.show(gone["id"], views.order_view(ORDER))
    s.show(kept["id"], views.list_view("Sam Carter's alterations", ["Hem the trousers"]))
    durable = path.read_bytes()
    _placed, restore = _flaky_record_flush(monkeypatch, fail_from=1, records_only=True)
    with pytest.raises(NotDurable):
        s.show(gone["id"], None)                     # made: its journal is durable
    restore()
    _placed, restore = _flaky_record_flush(monkeypatch, fail_from=1)
    with pytest.raises(NotSaved):
        s.show(kept["id"], None)                     # not made: nothing durable holds it
    restore()
    owed = json.loads(s.journal_path.read_text())["screens"]
    assert set(owed) == {gone["id"]}, "the journal is back to what is owed"
    path.write_bytes(durable)                         # the power goes before any record is durable
    restarted = DisplayStore(path, mono=Tick())
    assert restarted.poll(gone["id"], gone["screen_key"])["showing"] is None
    assert restarted.poll(kept["id"], kept["screen_key"])["showing"]["title"] == "Sam Carter's alterations"
    assert "E8 1AA" not in path.read_text()


# --------------------------------------------------------------------------- B-04


def test_a_key_holder_that_never_draws_a_page_is_held_to_the_servers_plan_and_its_done_is_its_word(s):
    """B-04 (demonstrated): a screen holding its key and an allowed login could acknowledge
    client-chosen ranges without any page being issued and send confirm:true, and the done
    record called that "packed". What the server can decide, it now does: the first page sets
    the plan's page size, the server issues the plan — every page that size but the last, each
    starting where the one before ended — says it back with every acknowledgement, and takes
    only the plan's next page, a second after the last. What it cannot decide it says plainly:
    these are direct, paced POSTs that never render a page, and they still mark the order done —
    so the done row records that it was marked with the screen's own button (`how` "screen"),
    and CLIVE says it as that screen's word, not a check. The owner's remote, every item ticked
    on his own device, is recorded as "remote". Whether a screen's word is to count as packed is
    the owner's ruling, not this code's."""
    from app.tools import display_tools

    client = app_with(s)
    screen = pair(s, "Packing screen")
    sid = screen["id"]
    mine = as_screen(screen["screen_key"])
    many = dict(ORDER, items=[dict(ORDER["items"][1], title=f"Tee {i}", sku=f"SKU-{i}") for i in range(20)])
    s.show(sid, views.order_view(many))

    def seen(start, end):
        return client.post(f"/displays/{sid}/seen", json={"version": 1, "start": start, "end": end}, headers=mine)

    first = seen(0, 5).json()
    assert first == {"seen": 5, "plan": {"size": 5, "pages": 4, "covered": 5, "next": [5, 10]}}
    later(s)
    for start, end in ((5, 9), (5, 11), (6, 11), (10, 15), (4, 9)):
        refused = seen(start, end)
        assert refused.status_code == 409 and refused.json()["code"] == "out_of_order", (start, end)
        assert refused.json()["next"] == [5, 10], "the page the plan takes next"
    assert seen(0, 20).status_code == 409, "never the whole order in one word"
    for start in (5, 10, 15):
        later(s)
        assert seen(start, start + 5).json()["plan"]["covered"] == start + 5
    assert s.page_plan(sid, 1) == {"size": 5, "pages": 4, "covered": 20, "next": None}
    later(s)
    done = client.post(f"/displays/{sid}/done", json={"version": 1, "confirm": True}, headers=mine)
    assert done.status_code == 200
    row = s.done()[0]
    assert row["how"] == "screen" and row["by"] == OWNER_LOGIN
    listed = run(display_tools.screen_list(order_id=ORDER["order_id"]))
    assert listed["done"][0]["marked"] == "marked packed with the Packing screen's own button: that screen's word, not a check"
    # The remote's done: the owner's ticks, item by item, from his own device.
    s.show(sid, views.list_view("Today", ["One", "Two"]))
    v = s.remote(sid)["panes"][0]["v"]
    s.tick(sid, 0, 0, True, v)
    s.tick(sid, 0, 1, True, v)
    s.done_from_remote(sid, 0, v, by=OWNER_LOGIN)
    assert s.done()[0]["how"] == "remote"
    said = run(display_tools.screen_list())["done"][0]["marked"]
    assert said == "marked done from the owner's remote for the Packing screen, with every item ticked there"


def test_a_done_row_from_before_says_nothing_it_does_not_know(tmp_path):
    """B-04: a row written before `how` was kept may have been either, and is said as neither."""
    path = tmp_path / "displays.json"
    path.write_text(json.dumps({"screens": {}, "done": [{
        "kind": "order", "ref": "gid://shopify/Order/1", "title": "Order #1", "at": "2999-01-01T00:00:00+00:00",
        "screen": "Packing screen", "screen_id": "scr_0123456789ab", "by": OWNER_LOGIN, "how": "a test's word"}]}),
        encoding="utf-8")
    row = DisplayStore(path).done()[0]
    assert row["how"] is None and store_module.how_marked(row) == "marked packed on the Packing screen"


# --------------------------------------------------------------------------- B-NEW-DONE-LOSS


def _largest_order(n: int) -> dict:
    """An order slip as large as a screen takes: views.MAX_ITEMS items and every field at its
    longest, in two-byte letters, the image addresses grown until the view is just under
    views.MAX_VIEW_BYTES."""
    def wide(k: int) -> str:
        return "é" * k

    def order(image: int) -> dict:
        return {
            "order_id": f"gid://shopify/Order/{n}", "order_number": f"#{n}", "placed_at": wide(40),
            "customer_name": wide(80), "note": wide(600), "tags": [wide(40)] * 10, "payment": wide(40),
            "fulfillment": wide(40), "shipping_method": wide(80),
            "shipping_address": {"name": wide(80), "company": wide(80), "phone": wide(40), "lines": [wide(120)] * 6,
                                 "city": wide(80), "province": wide(80), "zip": wide(20), "country": wide(60)},
            "items": [{"title": wide(120), "variant": wide(80), "sku": wide(60), "quantity": 99_999, "current_quantity": 99_999,
                       "unfulfilled_quantity": 99_999, "image_url": "https://cdn.example.com/" + "i" * image}
                      for _ in range(views.MAX_ITEMS)],
        }

    image = 0
    while image < 470 and len(json.dumps(views.order_view(order(image + 10)), ensure_ascii=False).encode()) < views.MAX_VIEW_BYTES:
        image += 10
    view = views.order_view(order(image))
    size = len(json.dumps(view, ensure_ascii=False).encode())
    assert views.MAX_VIEW_BYTES - 1000 < size < views.MAX_VIEW_BYTES
    return view


def _full_done_record() -> list[dict]:
    """MAX_DONE done rows, every field at its longest, none of them old enough to age out."""
    return [{"kind": "order", "ref": f"gid://shopify/Order/{n:020d}", "title": f"Order #{n:012d}",
             "at": "2999-01-01T00:00:00+00:00" + "0" * 15, "screen": "é" * 40, "screen_id": "scr_000000000000",
             "by": "b" * 80, "how": "remote"} for n in range(MAX_DONE)]


def test_every_screen_showing_two_of_the_largest_views_beside_a_full_done_record_loses_nothing(tmp_path):
    """B-NEW-DONE-LOSS (round 9): with two views allowed on each of twenty screens, _write threw
    away the oldest half of the done record, again and again, until the file fitted — silently.
    Now no done row is ever dropped but by its age or MAX_DONE, and the record's bound holds
    what the screens can show: every screen with two of the largest views, every item ticked,
    beside a full done record, fits, and the done record comes through whole, across a restart."""
    path = tmp_path / "displays.json"
    s = DisplayStore(path, mono=Tick())
    rows = _full_done_record()
    s._data["done"] = [DisplayStore._done_row(r) for r in rows]
    s._write()
    big = [_largest_order(n) for n in (1001, 1002)]
    made = [pair(s, f"{'é' * 36} {i:03d}") for i in range(MAX_SCREENS)]
    for screen in made:
        s.show(screen["id"], big[0])
        s.show(screen["id"], big[1], beside=True)
    # Every item ticked on every pane (set straight in: forty-eight hundred writes of a full
    # record prove nothing more), then one more real change through the store's own check.
    for screen in s._data["screens"].values():
        for key in ("showing", "beside"):
            screen[key]["ticked"] = list(range(views.MAX_ITEMS))
    last = made[-1]
    s.tick(last["id"], 1, 0, False, s.remote(last["id"])["panes"][1]["v"])
    size = path.stat().st_size
    assert size < store_module.MAX_FILE_BYTES, size
    assert len(s._data["done"]) == MAX_DONE and s.done(limit=MAX_DONE) == list(reversed([DisplayStore._done_row(r) for r in rows]))
    restarted = DisplayStore(path, mono=Tick())
    assert restarted.done(limit=MAX_DONE) == s.done(limit=MAX_DONE)
    assert all(len([p for p in (x["showing"], x["beside"]) if p]) == 2 for x in restarted._data["screens"].values())


def test_a_change_that_would_overflow_the_record_is_refused_with_nothing_changed_and_no_done_row_lost(tmp_path, monkeypatch):
    """B-NEW-DONE-LOSS: past the bound, the change is refused (Full) in plain words, before
    anything is written: the record in memory and on disk is as it was, and every done row is
    still there. What makes the record no larger — taking something off — still goes through.
    CLIVE and the remote say it as it is."""
    from app.tools import display_tools

    path = tmp_path / "objectives" / "displays.json"
    s = store_module.install(path, mono=Tick())
    screen = pair(s, "Packing screen")
    s._data["done"] = [DisplayStore._done_row(r) for r in _full_done_record()]
    s._write()
    s.show(screen["id"], views.list_view("Today", ["One"]))
    monkeypatch.setattr(store_module, "MAX_FILE_BYTES", path.stat().st_size + 200)
    before, done = path.read_bytes(), s.done(limit=MAX_DONE)
    with pytest.raises(Full, match="record of its screens is full, so that was not done and nothing was changed"):
        s.show(screen["id"], views.order_view(ORDER), beside=True)
    assert path.read_bytes() == before and s.done(limit=MAX_DONE) == done and len(done) == MAX_DONE
    assert [p["title"] for p in (s._data["screens"][screen["id"]]["showing"],)] == ["Today"]
    assert s._data["screens"][screen["id"]]["beside"] is None
    with pytest.raises(ToolError, match="record of its screens is full"):
        run(display_tools.screen_show(screen="Packing screen", title="Tomorrow", lines=["x" * 200] * 40, beside=True))
    client = app_with(s)
    v = s.remote(screen["id"])["panes"][0]["v"]
    monkeypatch.setattr(store_module, "MAX_FILE_BYTES", 1000)
    ticked = client.post(f"/displays/{screen['id']}/remote/tick", json={"pane": 0, "item": 0, "packed": True, "version": v},
                         headers=OWNER)
    assert ticked.status_code == 409 and ticked.json()["code"] == "full"
    # Taking the list off makes the record smaller: never refused for its size.
    s.take_off(screen["id"])
    assert s._data["screens"][screen["id"]]["showing"] is None and len(s.done(limit=MAX_DONE)) == MAX_DONE


def test_every_answer_to_a_screens_ask_says_which_build_answered(s):
    """A screen left open across a deploy reloads itself once it rests (web/display.js), so every
    answer to its ask says which build of CLIVE gave it: in full, and "nothing new" alike."""
    from tests.test_displays import app_with, as_screen, pair

    client = app_with(s)
    client.app.state.runtime.build = "build-7"
    made = pair(s, "Packing screen")
    full = client.get(f"/displays/{made['id']}?v=-1", headers=as_screen(made["screen_key"]))
    assert full.status_code == 200 and full.headers["x-clive-build"] == "build-7"
    quiet = client.get(f"/displays/{made['id']}?v={full.json()['version']}", headers=as_screen(made["screen_key"]))
    assert quiet.status_code == 204 and quiet.headers["x-clive-build"] == "build-7"
