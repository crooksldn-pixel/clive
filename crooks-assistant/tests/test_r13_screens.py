"""Round 13 of the deploy review: the owner's screens, the server's side.

- S3-01 (RC-12): a record the owner drops on a screen goes to the screen the route checked by its
  id, and to no other. Between the route's check and the tool's own look-up by name, the Office TV
  can be forgotten and a new device named "Office TV" and approved; the drop must not go to that
  new device. The screen's id is the route's own: the model can pass none.
- S3-02 (RC-6): a change the owner makes from his remote is not answered as saved until it is
  kept. When the folder's flush fails the answer is a retryable 503, and a retry does not apply
  the change twice.
- R9-B2-B2-01, screens-server (RC-6): a key handed over in a rotation whose record was not kept
  durably still opens the screen after a power cut brings the old record back; the old key stays
  valid alongside it until the next durable write, and not after.

Everything goes through the real app where a person would: the door, the screens router, the
route, the dispatcher and the gate (tests/test_screen_paths.py world). The model, Shopify and the
disk's failure are what stand in.
"""

from __future__ import annotations

import pytest

from app.tools import display_tools
from tests.test_context import ORDER
from tests.test_displays import pair
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
