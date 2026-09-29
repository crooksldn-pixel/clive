"""Round 13 of the deploy review: the owner's screens, the server's side.

- S3-01 (RC-12): a record the owner drops on a screen goes to the screen the route checked by its
  id, and to no other. Between the route's check and the tool's own look-up by name, the Office TV
  can be forgotten and a new device named "Office TV" and approved; the drop must not go to that
  new device. The screen's id is the route's own: the model can pass none.
- S3-02 (RC-6): a change the owner makes from his remote is not answered as saved until it is
  kept. When the folder's flush fails the answer is a retryable 503, and a retry does not apply
  the change twice.
- R9-B2-B2-01, screens-server (RC-6): a key is handed over only once the record that holds it is
  kept durably, so a power cut can never bring back a record the screen's key does not open. A
  change of key whose record could not be kept is refused (503, no cookie) and the key the screen
  already has goes on working.

Everything goes through the real app where a person would: the door, the screens router, the
route, the dispatcher and the gate (tests/test_screen_paths.py world). The model, Shopify and the
disk's failure are what stand in.
"""

from __future__ import annotations

import itertools

import pytest

from app.displays import store as store_module
from app.displays import views
from app.displays.store import DisplayStore, NotSaved, NotThisScreen
from app.tools import display_tools
from tests.test_context import ORDER
from tests.test_displays import ORDER as SLIP
from tests.test_displays import OWNER, Tick, app_with, as_screen, handed_key, pair
from tests.test_r11_screens_server import Disk
from tests.test_r12_put_on_screen import drop, looked_up, shop, showing  # noqa: F401 (the fixture)
from tests.test_screen_paths import MINE, world  # noqa: F401 (the fixture)

# --------------------------------------------------------------------------- S3-01


async def test_a_drop_goes_to_the_screen_the_route_checked_and_never_to_a_new_one_of_the_same_name(world, shop, monkeypatch):  # noqa: F811
    """The Office TV is checked by its id; before the tool looks it up by name, it is forgotten and
    a new device is named "Office TV" and approved. On the code before round 13 the order's slip,
    customer and address, went to the new device while the answer named the old one's id."""
    screens = world.screens
    tv = pair(screens, "Office TV")
    await looked_up(world)
    real_find = type(screens).find
    swapped: dict = {}

    def find(self, name, *, exact=False):
        if not swapped:
            assert self.forget(tv["id"]) is True
            swapped["new"] = pair(self, "Office TV")
        return real_find(self, name, exact=exact)

    monkeypatch.setattr(type(screens), "find", find)
    answer = await drop(world, tv["id"])
    assert swapped, "the tool looked the screen up by name after the route checked it"
    assert answer.status_code == 409, answer.text
    assert answer.json()["code"] == "not_shown"
    assert "Office TV" in answer.json()["detail"]
    new = swapped["new"]
    assert showing(screens, new) == (None, None), "nothing went on the new device"
    assert screens.get(tv["id"]) is None


async def test_the_screen_the_route_checked_still_takes_the_drop(world, shop):  # noqa: F811
    """The binding changes nothing for an ordinary drop, nor for the owner's spoken request after
    it: the route's id is its own call's, and no later call inherits it."""
    screens = world.screens
    office, packing = pair(screens, "Office TV"), pair(screens, "Packing screen")
    await looked_up(world)
    answer = await drop(world, office["id"])
    assert answer.status_code == 200, answer.text
    assert answer.json()["screen_id"] == office["id"]
    assert showing(screens, office)[0]["ref"] == ORDER
    world.model.script = [("screen_show", {"screen": "Packing screen", "order_id": ORDER})]
    said = await world.client.post("/turn", json={"text": "put 1938 on the packing screen", "session_id": "s1"}, headers=MINE)
    assert said.status_code == 200
    assert showing(screens, packing)[0]["ref"] == ORDER
    assert display_tools.DROP_SCREEN.get() == ""


async def test_the_model_cannot_name_a_screen_by_its_id(world, shop):  # noqa: F811
    """The id is not in screen_show's schema and not in its signature, so a model that makes one up
    is refused by the tool call itself and nothing goes on any screen."""
    import inspect

    from app.tools import registry

    spec = registry.get(display_tools.SHOW_TOOL)
    assert "screen_id" not in spec.input_schema["properties"]
    assert "screen_id" not in inspect.signature(display_tools.screen_show).parameters
    screens = world.screens
    office, other = pair(screens, "Office TV"), pair(screens, "Stock room")
    await looked_up(world)
    world.model.script = [("screen_show", {"screen": "Office TV", "order_id": ORDER, "screen_id": other["id"]})]
    said = await world.client.post("/turn", json={"text": "put 1938 on the office tv", "session_id": "s1"}, headers=MINE)
    assert said.status_code == 200
    assert showing(screens, office) == (None, None)
    assert showing(screens, other) == (None, None)


@pytest.mark.parametrize("bound", ["scr_000000000000", ""])
async def test_the_tool_refuses_a_name_that_is_not_the_bound_screen(world, shop, bound):  # noqa: F811
    """The tool's own rule, called as the route calls it: bound to one screen's id, a name that
    resolves to any other screen is refused before anything is read; unbound, the name decides."""
    from app.tools import authority
    from app.tools.registry import ToolError
    from tests.test_displays import OWNER_LOGIN

    screens = world.screens
    office = pair(screens, "Office TV")
    held = authority.TOOL_AUTHORITY.set(authority.for_owner(OWNER_LOGIN))
    token = display_tools.DROP_SCREEN.set(bound)
    try:
        if bound:
            with pytest.raises(ToolError, match="not the screen"):
                await display_tools.screen_show("Office TV", title="Today", lines=["One"])
            assert showing(screens, office) == (None, None)
        else:
            out = await display_tools.screen_show("Office TV", title="Today", lines=["One"])
            assert out["screen"] == "Office TV"
    finally:
        display_tools.DROP_SCREEN.reset(token)
        authority.TOOL_AUTHORITY.reset(held)


# --------------------------------------------------------------------------- S3-02


def _broken(folder):
    raise OSError(5, "I/O error")


def test_a_tick_the_disk_could_not_keep_is_answered_503_and_a_retry_ticks_it_once(tmp_path, monkeypatch):
    """The owner ticks an item on his remote while the screens' folder cannot be flushed. On the
    code before round 13 he was answered 200 although the tick might not outlive a power cut. Now
    he is answered 503 (not saved, nothing changed: the remote and the screen are not shown it),
    and the same tap again, once the disk is well, ticks it, once, and it is on disk."""
    path = tmp_path / "objectives" / "displays.json"
    s = store_module.install(path, mono=Tick())
    client = app_with(s)
    tv = pair(s, "Packing screen")
    s.show(tv["id"], views.order_view(SLIP))
    pane = client.get(f"/displays/{tv['id']}/remote", headers=OWNER).json()["panes"][0]
    tap = {"pane": 0, "item": pane["items"][0]["i"], "packed": True, "version": pane["v"]}
    ticked = lambda: [it["i"] for it in client.get(f"/displays/{tv['id']}/remote", headers=OWNER).json()["panes"][0]["items"] if it["ticked"]]  # noqa: E731

    real = store_module._fsync_dir
    monkeypatch.setattr(store_module, "_fsync_dir", _broken)
    for _ in range(2):                                     # tapped, and tapped again while the disk still fails
        said = client.post(f"/displays/{tv['id']}/remote/tick", json=tap, headers=OWNER)
        assert said.status_code == 503, said.text
        assert said.json()["code"] == "not_saved" and "nothing was changed" in said.json()["detail"]
        assert ticked() == [], "not shown as ticked: it was not made"
        assert s.poll(tv["id"], tv["screen_key"])["showing"].get("ticked") in (None, [])
    assert s.unsaved, "and housekeeping keeps trying to make the record durable"

    monkeypatch.setattr(store_module, "_fsync_dir", real)
    for _ in range(2):                                     # the retry, and one more: the same tick, once
        said = client.post(f"/displays/{tv['id']}/remote/tick", json=tap, headers=OWNER)
        assert said.status_code == 200, said.text
        assert said.json()["ticked"] == [tap["item"]]
    assert ticked() == [tap["item"]]
    assert not s.unsaved
    restarted = DisplayStore(path, mono=Tick())
    assert restarted.poll(tv["id"], tv["screen_key"])["showing"]["ticked"] == [tap["item"]], "on disk"


def test_an_approval_the_disk_could_not_keep_is_not_made_and_the_code_still_approves_it(tmp_path, monkeypatch):
    """The owner reads out a new screen's code while the folder cannot be flushed. On the code before
    round 13 the screen was approved in memory and he was told so, though a power cut could
    undo it. Now nothing is approved and he is told to try again; the same code approves it once
    the disk is well, and the approval is on disk."""
    path = tmp_path / "objectives" / "displays.json"
    s = DisplayStore(path, mono=Tick())
    made = s.register("Office screen")
    real = store_module._fsync_dir
    monkeypatch.setattr(store_module, "_fsync_dir", _broken)
    with pytest.raises(NotSaved, match="nothing was changed"):
        s.approve("Office screen", made["code"])
    assert s.poll(made["id"], made["screen_key"])["pending"] is True, "not approved"
    with pytest.raises(NotSaved):
        s.approve("Office screen", made["code"])          # said again while the disk still fails
    monkeypatch.setattr(store_module, "_fsync_dir", real)
    assert s.approve("Office screen", made["code"]) == {"screen": "Office screen", "approved": True}
    assert DisplayStore(path, mono=Tick()).poll(made["id"], made["screen_key"])["pending"] is False, "on disk"


def test_the_screen_pair_tool_says_an_approval_was_not_saved(tmp_path, monkeypatch):
    """The same through the tool the owner's spoken code reaches: its words, not a success."""
    from types import SimpleNamespace

    from app.tools import authority
    from app.tools.context import CURRENT_SESSION
    from app.tools.registry import ToolError
    from tests.test_displays import OWNER_LOGIN, run

    s = store_module.install(tmp_path / "objectives" / "displays.json", mono=Tick())
    made = s.register("Office screen")
    spoken = " ".join(made["code"])
    held = authority.TOOL_AUTHORITY.set(authority.for_owner(OWNER_LOGIN))
    session = CURRENT_SESSION.set(SimpleNamespace(heard=f"approve the office screen, code {spoken}"))
    try:
        monkeypatch.setattr(store_module, "_fsync_dir", _broken)
        with pytest.raises(ToolError, match="nothing was changed"):
            run(display_tools.screen_pair("Office screen", made["code"]))
        assert s.get(made["id"])["paired"] is False
    finally:
        CURRENT_SESSION.reset(session)
        authority.TOOL_AUTHORITY.reset(held)


# --------------------------------------------------------------------------- R9-B2-B2-01 (screens-server)


def _opens(store: DisplayStore, sid: str, key: str) -> bool:
    try:
        return store.poll(sid, key) is not None
    except NotThisScreen:
        return False


@pytest.mark.parametrize("owed", [False, True], ids=["nothing owed", "a deletion owed"])
@pytest.mark.parametrize("held_as", ["cookie", "legacy"])
def test_a_key_is_handed_over_only_once_it_opens_the_screen_however_the_power_goes(tmp_path, monkeypatch, held_as, owed):
    """A screen names itself again and its key is changed (a page from before round 10 handing its
    stored key in, or a screen with its cookie), with the disk failing at every combination of the
    change's operations, and then every way a power cut could leave the folder. On the code before
    round 13 the new key was handed over when the record holding it was in place but not flushed:
    a power cut could bring back the old record, where the new key opens nothing and the old key,
    which a copy of the page's storage may hold, opens the customer's slip again. Now:
    - a key handed over opens the screen in every state a power cut can leave, and the key it
      replaced opens it in none;
    - a change not made hands nothing over (503), and the key the device holds still opens the
      screen in the running store, and in every state once housekeeping has made the record
      durable again."""
    disk = Disk(monkeypatch)
    told: set[str] = set()
    case = itertools.count()
    # The change's own operations: the record put in place and flushed, and put back and flushed
    # when it is not made; with a deletion owed, the journal and the record written for it first.
    ops = 8 if owed else 4
    for size in range(ops + 1):
        for plan in itertools.combinations(range(ops), size):
            folder = tmp_path / f"case-{next(case)}"
            s = DisplayStore(folder / "displays.json", mono=Tick())
            tv = pair(s, "Packing screen")
            sid, old = tv["id"], tv["screen_key"]
            s.show(sid, views.order_view(SLIP))
            if owed:
                other = pair(s, "Office screen")
                s.show(other["id"], views.order_view(SLIP))
            disk.watch(folder)
            if owed:
                disk.mark({3})                            # a clear on the other screen: its record's flush fails
                with pytest.raises(store_module.NotDurable):
                    s.show(other["id"], None)
            disk.mark(set(plan))
            try:
                answer = s.register("Packing screen", **({"screen_key": old} if held_as == "cookie" else {"old_key": old}))
            except NotSaved:
                answer = None
            why = (held_as, owed, plan, "handed" if answer else "not made")
            told.add(why[3])
            if answer is not None:
                new = answer["screen_key"]
                assert new != old and _opens(s, sid, new) and not _opens(s, sid, old), why
                for restarted in disk.restarts(folder / "power-cut"):
                    assert _opens(restarted, sid, new), why
                    assert not _opens(restarted, sid, old), why
            else:
                assert _opens(s, sid, old), why
            disk.fail = set()
            assert s.sweep() == "", why
            key = new if answer is not None else old
            for restarted in disk.restarts(folder / "after-retry"):
                assert _opens(restarted, sid, key), why
                if answer is not None:
                    assert not _opens(restarted, sid, old), why
    assert told == {"handed", "not made"}, told


def test_a_key_change_the_disk_could_not_keep_is_answered_503_and_the_screen_keeps_working(tmp_path, monkeypatch):
    """The same through the route a screen's page calls, with the folder's flush failing: 503 and no
    cookie; the key it holds still opens it; named again once the disk is well, it is handed a
    new key and the old one opens nothing."""
    path = tmp_path / "objectives" / "displays.json"
    s = store_module.install(path, mono=Tick())
    client = app_with(s)
    tv = pair(s, "Packing screen")
    s.show(tv["id"], views.order_view(SLIP))
    real = store_module._fsync_dir
    monkeypatch.setattr(store_module, "_fsync_dir", _broken)
    refused = client.post("/displays/register", json={"name": "Packing screen"}, headers=as_screen(tv["screen_key"]))
    assert refused.status_code == 503 and refused.json()["code"] == "not_saved"
    assert "set-cookie" not in refused.headers
    assert client.get(f"/displays/{tv['id']}?v=-1", headers=as_screen(tv["screen_key"])).status_code == 200
    monkeypatch.setattr(store_module, "_fsync_dir", real)
    moved = client.post("/displays/register", json={"name": "Packing screen"}, headers=as_screen(tv["screen_key"]))
    assert moved.status_code == 200
    new = handed_key(moved)
    assert client.get(f"/displays/{tv['id']}?v=-1", headers=as_screen(new)).status_code == 200
    spent = client.get(f"/displays/{tv['id']}?v=-1", headers=as_screen(tv["screen_key"]))
    assert spent.status_code == 403 and spent.json()["code"] == "not_this_screen"
    assert _opens(DisplayStore(path, mono=Tick()), tv["id"], new)
