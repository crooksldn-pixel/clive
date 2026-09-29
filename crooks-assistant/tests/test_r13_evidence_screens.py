"""Round 13's evidence for the drop onto a screen: S3-03, S3T1-01, T5-01 and R9-B1-B-01-B-05-PATH.

Round 12's reviewers held the route and its tests but not the door or the dispatcher, and could
not tell whether an admitted owner could put a record on a screen with a conversation that was
never shown it (docs/review/deploy-review-round-12-findings.md). The rule, at this commit: the
door stamps the owner's authority (app/main.py guard_and_freshness); the route takes the
conversation only if it is this login's, the screen only if it is there and approved, and the
record only if the gate says THAT conversation was issued it (app/displays/put.py `_put`, the
gate's own `classify`) — all before the screen_show tool is dispatched, before Shopify is read,
and before the record of screens is written.

Here, through the real app with production's switches (tests/test_screen_paths.py `world`), every
refusal is watched at the two places a leak would go through: the dispatcher (no tool runs) and
the screen store's `show` (nothing is put up). Every name here is invented.
"""

from __future__ import annotations

import pytest

from app.displays import store as store_module
from app.tools import dispatch as dispatch_module
from tests.test_context import ORDER
from tests.test_displays import pair
from tests.test_r12_put_on_screen import (  # noqa: F401 (the fixture)
    CUSTOMER,
    drop,
    looked_up,
    shop,
    showing,
)
from tests.test_screen_paths import MINE, world  # noqa: F401 (the fixture)


@pytest.fixture()
def watched(monkeypatch):
    """Every screen_show the dispatcher is asked for, and every pane the screen store puts up."""
    ran: list[str] = []
    shown: list[str] = []
    real_dispatch, real_show = dispatch_module.dispatch, store_module.DisplayStore.show

    async def dispatch(name, args, **kwargs):
        ran.append(name)
        return await real_dispatch(name, args, **kwargs)

    def show(self, screen_id, *args, **kwargs):
        shown.append(screen_id)
        return real_show(self, screen_id, *args, **kwargs)

    monkeypatch.setattr(dispatch_module, "dispatch", dispatch)
    monkeypatch.setattr(store_module.DisplayStore, "show", show)
    return ran, shown


async def _his_other_conversation(app, session_id: str) -> None:
    """A conversation of his own, opened from his device, in which no order was looked up."""
    app.model.script = []
    opened = await app.client.post("/turn", json={"text": "good morning", "session_id": session_id}, headers=MINE)
    assert opened.status_code == 200, opened.text
    assert ORDER not in app.runtime.sessions.get(session_id).issued_ids


async def test_an_order_issued_to_one_conversation_posted_with_another_is_refused_before_anything_runs(
        world, shop, watched):  # noqa: F811 - the fixtures are tests/test_screen_paths.py world and test_r12_put_on_screen shop
    """The owner is admitted; conversation A looked order 1938 up, so A was issued it; the drop
    names the same order under conversation B, also his. Refused 403 `not_issued`: the tool is not
    dispatched, the screen store's `show` is never called, Shopify is not read, and the record of
    screens does not change by a byte. The same drop under A puts it up — the watch is real."""
    ran, shown = watched
    screens = world.screens
    tv = pair(screens, "Office TV")
    await looked_up(world, "sA")
    await _his_other_conversation(world, "sB")
    reads, record = len(shop.queries), screens.path.read_bytes()

    refused = await drop(world, tv["id"], session_id="sB")
    assert refused.status_code == 403 and refused.json()["code"] == "not_issued", refused.text
    for word in CUSTOMER:
        assert word not in refused.text, word
    assert ran == [] and shown == [], "no tool was dispatched and nothing was put on a screen"
    assert len(shop.queries) == reads, "the order was not read"
    assert screens.path.read_bytes() == record and showing(screens, tv) == (None, None)

    allowed = await drop(world, tv["id"], session_id="sA")
    assert allowed.status_code == 200, allowed.text
    assert ran == ["screen_show"] and shown == [tv["id"]]
    assert showing(screens, tv)[0]["ref"] == ORDER


async def test_a_pending_screen_or_another_logins_conversation_is_refused_before_anything_runs(
        world, shop, watched):  # noqa: F811 - the fixtures are tests/test_screen_paths.py world and test_r12_put_on_screen shop
    """The other two things the route settles before the tool: a screen still waiting for its code
    (409 `not_approved`) and a conversation that is another login's, even one that was shown the
    order (403 `wrong_session`). Neither dispatches the tool, reads the order or puts anything up."""
    ran, shown = watched
    screens = world.screens
    await looked_up(world, "sA")
    waiting = screens.register("Bedroom TV")
    reads, record = len(shop.queries), screens.path.read_bytes()
    pending = await drop(world, waiting["id"], session_id="sA")
    assert pending.status_code == 409 and pending.json()["code"] == "not_approved", pending.text

    theirs = world.runtime.sessions.get_or_create("theirs")
    theirs.login = "someone@example.com"
    theirs.issue(ORDER)
    tv = pair(screens, "Office TV")
    record = screens.path.read_bytes()
    other = await drop(world, tv["id"], session_id="theirs")
    assert other.status_code == 403 and other.json()["code"] == "wrong_session", other.text

    assert ran == [] and shown == [] and len(shop.queries) == reads
    assert screens.path.read_bytes() == record
    assert screens.poll(waiting["id"], waiting["screen_key"])["showing"] is None and showing(screens, tv) == (None, None)
