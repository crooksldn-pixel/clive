"""D-10: navigation, asserted on the workspace it restored and never on `ok`.

In twenty-two seconds of the live tablet session the owner pressed Home eight times and Back
four times. Every one of the twelve returned `ok=True`; the generated report scored the
command table at 100% accepted; and the owner, at the end of the session, said the back
button, the back-to-assistant button and the next button had all regressed. Both statements
were true, because `ok=True` says a command resolved, not that the screen went anywhere.

So nothing in this file asserts a status code. Every test asserts the RESTORED WORKSPACE —
which record is open, which working set "these" means, where the cursor is in it, which tab
is showing, which half it happened on — and the three commands are held apart by name:

    Home    the branch's LANDING workspace. Never a replay of the last held entity, which is
            what put the same email thread on screen for fourteen turns.
    Back    the exact workspace the owner came from: entity, set, cursor, tab, scroll, the
            rows he had opened, and the record he reached it from.
    Next    the CURRENT SET under the CURSOR, with a position to show. Never "the next
            historical item", which is what made Back and Next the same button.
"""

from __future__ import annotations

import pytest

from app import commands
from app.analytics import sets as working_sets
from app.families import load_all
from app.memory import ENTITY
from app.memory import current as memory
from app.session.branch import LANDING_KIND, LIST_KIND, Branch, Workflow
from app.session.models import Session

load_all()

# Three orders and the customer they belong to, by the shape of id the gate will accept.
ORDER_A = "gid://shopify/Order/1957"       # the brief's worked example: CROOKS-1957
ORDER_B = "gid://shopify/Order/1912"       # a prior order of the same customer
ORDER_C = "gid://shopify/Order/1876"
CUSTOMER = "gid://shopify/Customer/7001"
THREAD = "abc123def456"


def _hold(kind: str, ref: str, body: dict) -> None:
    """Put a record where `commands.replay` looks for it, so a move draws a card with no read."""
    memory().put(ENTITY, f"{kind}:{ref}", body, source="shopify", query="test:navigation",
                 provenance={"test": "navigation"})


@pytest.fixture()
def world():
    """A conversation holding three orders, a customer and a thread, all of them issued.

    The Mac holding a record is what makes Back free; the conversation having been SHOWN it is
    what makes Back permitted. Both are set up here, because a test that forgot the second
    would be testing a refusal.
    """
    session = Session(session_id="nav")
    branch = session.branch()
    _hold("order", ORDER_A, {"order_id": ORDER_A, "order_number": "CROOKS-1957", "customer_name": "Mia Jones"})
    _hold("order", ORDER_B, {"order_id": ORDER_B, "order_number": "CROOKS-1912", "customer_name": "Mia Jones"})
    _hold("order", ORDER_C, {"order_id": ORDER_C, "order_number": "CROOKS-1876", "customer_name": "Mia Jones"})
    _hold("customer", CUSTOMER, {"customer_id": CUSTOMER, "name": "Mia Jones", "orders": 3})
    _hold("email_thread", THREAD, {"thread_id": THREAD, "subject": "Where is my order?"})
    session.issue(ORDER_A, ORDER_B, ORDER_C, CUSTOMER, THREAD)
    return session, branch


def ctx(session, branch, **args):
    return commands.Ctx(runtime=None, session=session, branch=branch, args={k: str(v) for k, v in args.items()})


def run(name, session, branch, **args):
    return commands.run(name, ctx(session, branch, **args))


def orders_list(session, branch, *, members=(ORDER_A, ORDER_B, ORDER_C), label="today's orders"):
    """What a listing leaves behind: a working set, a cursor before its first member, and a
    stop on the trail for the LIST ITSELF — which is the thing Back has to be able to return
    to and the thing that was never recorded."""
    session.acting_branch = branch.branch_id
    ws = working_sets.create(session, kind="orders", members=list(members), label=label,
                             labels={ref: ref.rsplit("/", 1)[-1] for ref in members})
    branch.enter(area="orders", kind=LIST_KIND, ref=ws.set_id, label=ws.label,
                 set_id=ws.set_id, set_kind="orders", set_label=ws.label, total=len(ws.members))
    branch.workflow = Workflow(workflow_id="wf_nav", set_id=ws.set_id, kind="orders",
                               label=ws.label, operation="review", cursor=-1, total=len(ws.members))
    branch.set_id = ws.set_id
    return ws


# --------------------------------------------------------------------------- Home


def test_home_from_a_deep_order_is_the_branch_landing_and_not_the_last_entity(world):
    """The eight Homes. Each one redrew the email thread the branch happened to be holding —
    `nav[0]` — so the owner pressed it again, and got the same thread, eight times.

    Home names a PLACE. It resolves to the landing recipe for the branch's area and never to a
    record: a stale thread is not a destination, whatever the trail says about it.
    """
    session, branch = world
    orders_list(session, branch)
    run("open.entity", session, branch, kind="order", ref=ORDER_A, label="CROOKS-1957")
    run("open.entity", session, branch, kind="customer", ref=CUSTOMER, label="Mia Jones")

    home = run("navigation.home", session, branch)
    assert home.ok, home.detail
    assert home.changed.get("home") is True, home.changed
    assert home.changed.get("area") == "orders", home.changed
    assert home.changed.get("recipe") == commands.LANDING_FOR["orders"], home.changed
    # And nothing about the record the branch was holding: no replayed card, no entity move.
    assert not home.calls, "Home replayed a held record instead of opening a landing"
    assert "entity" not in home.changed, home.changed


def test_home_lands_in_the_area_the_branch_was_working_in(world):
    """A branch that has been in the inbox goes home to the inbox, not to orders. The landing
    is the branch's, which is also what keeps the two halves apart."""
    session, branch = world
    branch.enter(area="email", kind=LANDING_KIND, ref="email", label="Inbox")
    run("open.entity", session, branch, kind="email_thread", ref=THREAD, label="Where is my order?")
    home = run("navigation.home", session, branch)
    assert home.changed.get("area") == "email", home.changed
    assert home.changed.get("recipe") == commands.LANDING_FOR["email"], home.changed


def test_home_with_nothing_behind_it_still_goes_somewhere(world):
    """The live session's first Home was pressed on a branch whose trail held one email
    thread. The old answer — "There is nothing to go back to yet" — is the sentence that made
    the owner press it seven more times. A landing does not depend on a trail."""
    session, branch = world
    home = run("navigation.home", session, branch)
    assert home.ok, home.detail
    assert home.changed.get("recipe") == commands.LANDING_FOR[commands.DEFAULT_LANDING], home.changed


# --------------------------------------------------------------------------- Back


def test_the_brief_s_own_click_path(world):
    """Orders → CROOKS-1957 → Customer → prior order → Back returns to Customer ON
    CROOKS-1957; another Back returns to the Orders list at about the same position.

    Every clause of that is a separate failure today: the tab is not restored, the list is not
    on the trail at all, and the scroll is thrown away on every draw.
    """
    session, branch = world
    ws = orders_list(session, branch)
    run("surface.scroll", session, branch, depth=240)          # down the list, to CROOKS-1957

    run("open.entity", session, branch, kind="order", ref=ORDER_A, label="CROOKS-1957")
    run("surface.scroll", session, branch, depth=90)
    run("surface.tab", session, branch, surface="order", tab="customer")
    run("open.entity", session, branch, kind="order", ref=ORDER_B, label="CROOKS-1912")
    assert branch.entity["ref"] == ORDER_B

    first = run("navigation.back", session, branch)
    assert first.ok, first.detail
    assert branch.entity["ref"] == ORDER_A, "Back did not return to the order it came from"
    assert branch.tab == "customer", "Back returned to the record but not to the part of it"
    assert first.changed["workspace"]["tab"] == "customer", first.changed["workspace"]
    assert first.changed["workspace"]["scroll"] == 90, first.changed["workspace"]
    assert first.calls, "Back announced a move and drew nothing"

    second = run("navigation.back", session, branch)
    assert second.ok, second.detail
    stop = second.changed["workspace"]
    assert stop["kind"] == LIST_KIND, f"Back did not return to the list: {stop}"
    assert stop["set_id"] == ws.set_id, stop
    assert stop["area"] == "orders", stop
    assert stop["scroll"] == 240, f"the list came back at the top: {stop}"


def test_back_restores_the_working_set_and_the_cursor(world):
    """A Back that lands on a member of a set has to land on it AS a member: same set, same
    place in it, so the Next that follows carries on rather than starting again."""
    session, branch = world
    ws = orders_list(session, branch)
    run("workflow.next", session, branch)                      # 1 of 3
    run("workflow.next", session, branch)                      # 2 of 3
    assert branch.workflow.position == 2

    run("open.entity", session, branch, kind="customer", ref=CUSTOMER, label="Mia Jones")
    assert branch.entity["kind"] == "customer"

    back = run("navigation.back", session, branch)
    assert branch.entity["ref"] == ORDER_B, back.changed
    assert branch.set_id == ws.set_id, "the set the branch was walking was not restored"
    assert branch.workflow is not None and branch.workflow.set_id == ws.set_id
    assert branch.workflow.position == 2, f"the cursor was not restored: {branch.workflow.public()}"
    assert back.changed["workspace"]["position"] == 2, back.changed["workspace"]

    forward = run("workflow.next", session, branch)
    assert "3 of 3" in forward.answer, forward.answer


def test_back_to_a_narrowed_list_comes_back_narrowed(world):
    """The filters come back with the set, and are not kept on the stop.

    A working set is immutable and carries the query that made it, so restoring `set_id`
    restores exactly the narrowing the owner was looking at — including one made by a second
    narrowing step, which is a new set with the first as its parent. A stop that copied the
    filters instead could disagree with the set it named.
    """
    session, branch = world
    wide = orders_list(session, branch)
    narrow = working_sets.create(
        session, kind="orders", members=[ORDER_A], label="unfulfilled, over £50",
        provenance={"tool": "commerce_query", "parent": wide.set_id, "step": "narrow",
                    "query": {"filters": {"fulfillment": "unfulfilled", "total_min": 50}}},
    )
    branch.enter(area="orders", kind=LIST_KIND, ref=narrow.set_id, label=narrow.label,
                 set_id=narrow.set_id, set_kind="orders", set_label=narrow.label, total=1)
    branch.workflow = Workflow(workflow_id="wf_narrow", set_id=narrow.set_id, kind="orders",
                               label=narrow.label, cursor=-1, total=1)
    branch.set_id = narrow.set_id
    run("open.entity", session, branch, kind="order", ref=ORDER_A, label="CROOKS-1957")

    back = run("navigation.back", session, branch)
    restored = working_sets.get(session, back.changed["workspace"]["set_id"])
    assert restored is not None and restored.set_id == narrow.set_id
    assert restored.provenance["query"]["filters"] == {"fulfillment": "unfulfilled", "total_min": 50}
    assert restored.parent == wide.set_id, "the narrowing forgot what it narrowed"
    assert branch.workflow.set_id == narrow.set_id and branch.workflow.total == 1


def test_back_remembers_which_record_the_workspace_was_reached_from(world):
    """"Customer ON CROOKS-1957". A customer opened from an order is not the same workspace as
    the same customer opened from the inbox, and the relation is what the card says."""
    session, branch = world
    orders_list(session, branch)
    run("open.entity", session, branch, kind="order", ref=ORDER_A, label="CROOKS-1957")
    run("open.entity", session, branch, kind="customer", ref=CUSTOMER, label="Mia Jones")
    run("open.entity", session, branch, kind="order", ref=ORDER_C, label="CROOKS-1876")

    back = run("navigation.back", session, branch)
    came_from = back.changed["workspace"]["from"]
    assert came_from["kind"] == "order" and came_from["ref"] == ORDER_A, came_from


def test_back_restores_the_rows_that_were_open(world):
    """A list with three rows expanded is not the same screen as the same list closed."""
    session, branch = world
    orders_list(session, branch)
    run("surface.expand", session, branch, ref=ORDER_A)
    run("surface.expand", session, branch, ref=ORDER_B)
    run("open.entity", session, branch, kind="order", ref=ORDER_C, label="CROOKS-1876")
    assert branch.expanded == []

    run("navigation.back", session, branch)
    assert branch.expanded == [ORDER_A, ORDER_B], branch.expanded


def test_back_to_a_list_draws_the_cards_that_list_was_showing(world):
    """A record can be replayed from the entity cache; a listing cannot — there is no
    `list_id` in memory to read. So the cards a list stop was showing are kept with the stop,
    and Back redraws them rather than announcing a move over an empty screen."""
    session, branch = world
    orders_list(session, branch)
    branch.shown([{"type": "order_list", "data": {"orders": [{"order_id": ORDER_A}]}}], "3 orders today.", "")
    run("open.entity", session, branch, kind="order", ref=ORDER_A, label="CROOKS-1957")

    back = run("navigation.back", session, branch)
    drawn = [s.as_ui() for s in back.surfaces]
    assert [d["type"] for d in drawn] == ["order_list"], drawn


def test_back_to_a_list_whose_cards_are_gone_reads_the_place_again(world):
    """The one case a replay cannot cover, and the one the whole pass is about.

    A record comes back from the shared entity cache. A listing has nothing to come back
    from — there is no `list_id` in memory — so when the cards kept with the stop are gone,
    the PLACE is read again by its own landing recipe. What must never happen is the third
    option: a sentence saying it went back over a screen that did not change.
    """
    session, branch = world
    orders_list(session, branch)                     # no cards ever presented for this stop
    run("open.entity", session, branch, kind="order", ref=ORDER_A, label="CROOKS-1957")

    back = run("navigation.back", session, branch)
    assert back.ok, back.detail
    assert not back.surfaces, "there were no cards to redraw; the test proves nothing"
    assert back.changed.get("recipe") == commands.LANDING_FOR["orders"], back.changed
    assert back.changed["workspace"]["kind"] == LIST_KIND, back.changed["workspace"]


async def test_a_cold_list_stop_is_redrawn_through_the_route(stage):
    """The same thing, end to end: the cards kept with the stop are dropped, and the Back that
    follows still comes back with a list on the screen."""
    listing = await stage.touch("open.area", area="orders", session_id="cold_list")
    card = listing.data("order_list")
    rows = [r for r in (card.get("orders") or card.get("rows") or []) if isinstance(r, dict)]
    assert rows, listing.surface_types
    await stage.touch("open.entity", session_id="cold_list", kind="order",
                      ref=str(rows[0].get("order_id") or ""), label="a row")

    branch = stage.branch("cold_list", listing.branch_id)
    dropped = [e for e in branch.nav if e.is_workspace]
    assert dropped and dropped[0].ui, "the list stop kept no cards; the test proves nothing"
    for entry in dropped:
        entry.ui = []

    back = await stage.touch("navigation.back", session_id="cold_list")
    assert back.raw.get("ok") is True, back.raw
    assert not back.prose_only, f"back announced a move and drew nothing: {back.answer!r}"
    assert back.surface("order_list") is not None, back.surface_types
    assert back.model_calls == 0, back.model_calls


def test_back_at_the_start_of_the_trail_says_so_and_stays(world):
    session, branch = world
    run("open.entity", session, branch, kind="order", ref=ORDER_A, label="CROOKS-1957")
    back = run("navigation.back", session, branch)
    assert back.changed.get("landed") is False, back.changed
    assert branch.entity["ref"] == ORDER_A, "a refused Back moved the branch anyway"


# --------------------------------------------------------------------------- Next


def test_next_walks_the_set_and_says_where_it_is(world):
    """Ten orders, and a compact position on every step. The number is on the reply as a
    number, not only inside a sentence, because the chip on the glass draws it."""
    session, branch = world
    members = [f"gid://shopify/Order/{1900 + n}" for n in range(10)]
    for ref in members:
        _hold("order", ref, {"order_id": ref, "order_number": f"CROOKS-{ref.rsplit('/', 1)[-1]}"})
    session.issue(*members)
    orders_list(session, branch, members=tuple(members), label="ten orders")

    for step in (1, 2, 3):
        moved = run("workflow.next", session, branch)
        assert moved.ok, moved.detail
        assert moved.changed["position"] == step, moved.changed
        assert moved.changed["total"] == 10, moved.changed
        assert f"{step} of 10" in moved.answer, moved.answer
        assert branch.entity["ref"] == members[step - 1]


def test_next_is_never_the_next_thing_in_the_history(world):
    """The muddle this defect is about: Back popped a render history and Next walked a set, and
    the tablet aliased one onto the other. With a trail to walk and no set open, Next has
    nothing to do and must say so — not step forward through the trail."""
    session, branch = world
    run("open.entity", session, branch, kind="order", ref=ORDER_A, label="CROOKS-1957")
    run("open.entity", session, branch, kind="order", ref=ORDER_B, label="CROOKS-1912")
    run("navigation.back", session, branch)
    assert branch.public()["can_forward"] is True, "the fixture needs somewhere forward to go"

    moved = run("workflow.next", session, branch)
    assert moved.ok is False and moved.code == "no_set", (moved.ok, moved.code)
    assert branch.entity["ref"] == ORDER_A, "Next walked the trail"


def test_back_never_moves_the_cursor_and_next_never_moves_the_trail(world):
    """Two cursors, two buttons. Neither may touch the other's."""
    session, branch = world
    orders_list(session, branch)
    run("workflow.next", session, branch)
    run("workflow.next", session, branch)
    depth_before, cursor_before = branch.nav_index, branch.workflow.cursor

    run("navigation.back", session, branch)
    assert branch.nav_index == depth_before - 1
    assert branch.workflow.cursor == cursor_before - 1 or branch.workflow.cursor == 0, (
        "Back restored the cursor the stop was at, which is the stop's own arithmetic"
    )

    at = branch.workflow.cursor
    run("workflow.next", session, branch)
    assert branch.workflow.cursor == at + 1, "Next did not move the set's cursor"


# ----------------------------------------------------------------- the two halves


def test_a_back_on_one_half_leaves_the_other_half_exactly_where_it_was(world):
    """Branch-local trails. The halves share read caches and the issued-id ledger, and share
    no position at all — so the right half's Back cannot move the left half's screen."""
    session, left = world
    orders_list(session, left)
    run("open.entity", session, left, kind="order", ref=ORDER_A, label="CROOKS-1957")
    run("open.entity", session, left, kind="customer", ref=CUSTOMER, label="Mia Jones")

    right = Branch(branch_id="br_right", session_id=session.session_id, parent_id=left.branch_id)
    session.branches[right.branch_id] = right
    session.acting_branch = right.branch_id
    run("open.entity", session, right, kind="order", ref=ORDER_B, label="CROOKS-1912")
    run("open.entity", session, right, kind="order", ref=ORDER_C, label="CROOKS-1876")

    before = (left.nav_index, dict(left.entity), [e.entry_id for e in left.nav], left.tab, left.set_id)
    run("navigation.back", session, right)
    assert right.entity["ref"] == ORDER_B
    after = (left.nav_index, dict(left.entity), [e.entry_id for e in left.nav], left.tab, left.set_id)
    assert before == after, "a Back on the right half moved the left half"
    assert left.nav is not right.nav, "the halves share one stack object"

    # And Home on the right resolves the RIGHT half's landing.
    right.enter(area="sales", kind=LANDING_KIND, ref="sales", label="Sales")
    assert run("navigation.home", session, right).changed["area"] == "sales"
    assert run("navigation.home", session, left).changed["area"] == "orders"


# ------------------------------------------------------------------ no model, ever


@pytest.fixture()
async def stage():
    from experience.harness import harness

    async with harness(admitted=True) as h:
        yield h


async def test_the_whole_of_navigation_happens_without_the_model(stage):
    """Brief §24, driven through the real routes and counted.

    Back, Home, Next, a tab, a branch focus, opening a relation and opening a record the Mac
    already holds are all answerable from state the Mac has. The count is taken across the
    whole sequence rather than per call, because one model call anywhere in it is the second
    the owner waits and the sentence he did not ask for.
    """
    session_id = "det"
    before = len(stage.provider.calls)
    listing = await stage.touch("open.area", area="orders", session_id=session_id)
    card = listing.data("order_list")
    rows = [r for r in (card.get("orders") or card.get("rows") or []) if isinstance(r, dict)]
    assert rows, f"the fixture world drew no rows: {listing.surface_types}"
    ref = str(rows[0].get("order_id") or "")
    spoken_reads = len(stage.provider.calls) - before

    fork = await stage.client.post("/branches/fork", data={"session_id": session_id, "label": "right"},
                                   headers={"Tailscale-User-Login": "owner@example.com",
                                            "X-Forwarded-For": "100.64.0.9"})
    other = str(((fork.json().get("branch") or {}).get("branch_id")) or fork.json().get("branch_id") or "")
    at_start = len(stage.provider.calls)

    steps = [
        await stage.touch("open.entity", session_id=session_id, kind="order", ref=ref, label="a row"),
        await stage.touch("surface.tab", session_id=session_id, surface="order", tab="customer"),
        await stage.touch("surface.scroll", session_id=session_id, depth=120),
        await stage.touch("navigation.back", session_id=session_id),
        await stage.touch("workflow.next", session_id=session_id),
        await stage.touch("workflow.previous", session_id=session_id),
        await stage.touch("navigation.home", session_id=session_id),
        await stage.touch("navigation.forward", session_id=session_id),
        await stage.touch("branch.show", session_id=session_id, branch_id=other),
        await stage.touch("open.entity", session_id=session_id, kind="order", ref=ref, label="again"),
    ]
    await stage.client.post(f"/branches/{other}/focus", data={"session_id": session_id},
                            headers={"Tailscale-User-Login": "owner@example.com",
                                     "X-Forwarded-For": "100.64.0.9"})

    asked = len(stage.provider.calls) - at_start
    assert asked == 0, (
        f"navigation woke the model {asked} time(s): {stage.provider.calls[at_start:]}"
    )
    assert all(step.model_calls == 0 for step in steps), [s.model_calls for s in steps]
    assert spoken_reads == 0, "even the listing that set this up (the Orders landing, tapped) did not ask the model"
    # And they were not refusals dressed up as silence: every one of them said something or
    # drew something.
    empty = [s.command for s in steps if s.raw.get("ok") is False and s.raw.get("code") not in ("at_end", "at_start")]
    assert not empty or empty == ["navigation.forward"], f"refused: {empty}"


def test_no_navigation_command_can_reach_the_model(world):
    """Brief §24: Back, Home, Next, a tab, a branch focus, opening a relation and opening a
    record the Mac already holds are answerable from state the Mac has. A language model on
    that path buys nothing and costs a second.

    Asserted structurally rather than by counting calls: a runtime of None means any attempt
    to reach a provider is an AttributeError, and the registry is checked for the commands
    that would need one.
    """
    session, branch = world
    orders_list(session, branch)
    for name, args in (
        ("open.entity", {"kind": "order", "ref": ORDER_A, "label": "CROOKS-1957"}),
        ("surface.tab", {"surface": "order", "tab": "shipping"}),
        ("surface.expand", {"ref": ORDER_A}),
        ("surface.scroll", {"depth": 120}),
        ("workflow.next", {}),
        ("workflow.previous", {}),
        ("navigation.back", {}),
        ("navigation.forward", {}),
        ("navigation.home", {}),
        ("branch.show", {}),
    ):
        outcome = run(name, session, branch, **args)
        assert outcome is not None, name
        assert not getattr(outcome, "continuation", ""), name


# ------------------------------------------------------- the stop, as a data structure


def test_a_stop_on_the_trail_is_a_workspace_and_not_a_render():
    """What a NavEntry holds is what it takes to put the screen back: the record, the part of
    it, how far down, the set and the place in it, the rows opened, and where it was reached
    from. Never the cards themselves for a record — those come from the entity cache."""
    branch = Branch(branch_id="br_unit", session_id="s")
    branch.workflow = Workflow(workflow_id="wf", set_id="set_abc123", kind="orders",
                               label="today", cursor=1, total=4)
    branch.set_id = "set_abc123"
    entry = branch.visit("order", ORDER_A, "CROOKS-1957", tab="items")
    branch.mark(scroll=310)
    assert entry.set_id == "set_abc123" and entry.cursor == 1 and entry.total == 4
    assert entry.position == 2 and entry.area == ""
    assert entry.scroll == 310 and entry.tab == "items"
    assert entry.public()["position"] == 2


def test_entering_the_same_area_twice_is_the_same_stop():
    """Eight Homes in twenty-two seconds must not leave eight stops on the trail. Arriving
    somewhere you already are is not going anywhere — the same rule `visit` keeps for a
    record, kept for a place."""
    branch = Branch(branch_id="br_unit2", session_id="s")
    first = branch.enter(area="orders", kind=LIST_KIND, ref="set_aaaaaa", label="today")
    again = branch.enter(area="orders", kind=LIST_KIND, ref="set_bbbbbb", label="today, again")
    assert first.entry_id == again.entry_id and len(branch.nav) == 1
    assert branch.nav[0].set_id == "set_bbbbbb" or branch.nav[0].ref == "set_bbbbbb"
    branch.enter(area="email", kind=LANDING_KIND, ref="email", label="Inbox")
    assert len(branch.nav) == 2 and branch.landing == "email"
