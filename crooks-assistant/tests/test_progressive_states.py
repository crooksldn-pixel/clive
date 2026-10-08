"""The workspace as a thing with an IDENTITY and five states — §15, §27, D-2 and D-8.

Phase 4 made the screen arrive in pieces (tests/test_progressive.py holds that arithmetic).
The live session of 11 September shows what it still got wrong, and every test here is one of
those defects:

* **D-2** `renderOpts().tab` was ONE value per BRANCH, handed to every card that had tabs. He
  tapped Email once, on one customer, early in the session; from that moment every customer
  card on that branch opened on Email — all seven cards of `turn_be1b384ca420` included, drawn
  for seven customers he had never opened. His words at 20:18:12: *"I'm not seeing any UI here
  except email where there's nothing … I want to also be seeing his orders and his history"*.
  It was there, one tab away on the same card. So a tab belongs to a RECORD.
* **§15** a shell that says nothing is not progress. A compound task establishes what the
  workspace IS first — its name and the sections coming — and then each section is patched in
  place as it lands. The four numbers are renamed to say what they now measure.
* **§27** LOADING / PARTIAL / READY / EMPTY / ERROR, deliberately. **EMPTY IS NOT ERROR**: a
  read that found no threads keeps the workspace and says "No messages found" on the inbox
  section. An error in one section never destroys an unrelated one.
* **D-8** `turn_f0628fcf7be5` drew `order_list + working_set + folded` seven times, six of
  them in the same instant, while the owner was scrolling (26 scroll reports, deepest 971 px).

The tablet's half of all this is `tests/web/tabs.test.js`, run by Node at the bottom of this
file so one `pytest` proves both sides.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app import progressive
from app.presentation import UI_TYPES
from app.render import ADDED, DATA, render_id
from app.session.branch import Branch

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
UI_JS = (WEB / "ui.js").read_text(encoding="utf-8")
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_live_workspaces():
    progressive.reset()
    yield
    progressive.reset()


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def at(self, ms: float) -> None:
        self.t = ms / 1000.0


def orders(count: int = 7) -> dict:
    rows = [{"order_id": f"g{i}", "order_number": f"#19{i:02d}"} for i in range(count)]
    return {"type": "order_list", "data": {"title": "Today", "count": count, "orders": rows}}


def inbox(count: int = 4) -> dict:
    rows = [{"thread_id": f"t{i}", "subject": "Where is my order?"} for i in range(count)]
    return {"type": "email_list", "data": {"title": "Email", "count": count, "threads": rows}}


# --------------------------------------------------------------------------- D-2, on the Mac


def test_a_tab_tapped_on_one_customer_is_not_the_next_customers_tab():
    """The defect, in the state that caused it. One `tab` on the branch meant one tab for
    every record the branch ever drew."""
    branch = Branch(branch_id="br_1", session_id="s1")
    branch.visit("customer", "cus_6343", "Ada")
    branch.mark(tab="email", of="customer:cus_6343")
    assert branch.tab_for("customer", "cus_6343") == "email"
    # Seven customers he had never opened (turn_be1b384ca420's own ids).
    for ref in ("cus_4807", "cus_5015", "cus_4055", "cus_7975", "cus_2855", "cus_8887"):
        assert branch.tab_for("customer", ref) == "", f"{ref} inherited a tab tapped on another record"
    # And an order is not a customer either.
    assert branch.tab_for("order", "cus_6343") == ""


def test_the_tab_a_record_was_left_on_comes_back_with_that_record():
    """The half of the old behaviour that was worth keeping: returning to a card the owner
    had left on a tab restores THAT card's tab."""
    branch = Branch(branch_id="br_1", session_id="s1")
    branch.visit("customer", "cus_6343", "Ada")
    branch.mark(tab="email", of="customer:cus_6343")
    branch.visit("customer", "cus_4807", "Bea")
    branch.mark(tab="orders", of="customer:cus_4807")
    assert branch.tab_for("customer", "cus_6343") == "email"
    assert branch.tab_for("customer", "cus_4807") == "orders"
    # The map is what the tablet is handed, keyed by the render identity it draws cards by.
    assert branch.public()["tabs"] == {"customer:cus_6343": "email", "customer:cus_4807": "orders"}
    assert render_id({"type": "customer", "data": {"customer_id": "cus_6343"}}) in branch.public()["tabs"]


def test_the_tab_a_recipe_arrives_on_is_that_records_tab():
    """The task-implied tab belongs to the record it was implied for.

    A move that arrives on a tab — a customer opened on Orders, an address change on
    Shipping — used to set `Branch.tab`, which was then handed to every card on the half; now
    it reaches the RECORD, which is what makes "see his orders and his history" open on Orders
    for that customer and on nothing for any other.
    """
    branch = Branch(branch_id="br_1", session_id="s1")
    branch.visit("customer", "cus_6343", "Ada", tab="orders")
    assert branch.tab_for("customer", "cus_6343") == "orders"
    branch.visit("order", "g1", "#1938", tab="shipping")
    assert branch.tab_for("order", "g1") == "shipping"
    # The customer is still on Orders: arriving at the order did not move him.
    assert branch.tab_for("customer", "cus_6343") == "orders"
    # And a record the turn never named has no tab at all.
    assert branch.tab_for("customer", "cus_4807") == ""


def test_the_record_a_tab_belongs_to_defaults_to_the_one_on_screen():
    """A tap reported without saying which record it was on — the spoken "show me the
    shipping", which goes through `surface.tab` — belongs to the record the branch is on."""
    branch = Branch(branch_id="br_1", session_id="s1")
    branch.visit("order", "g1", "#1938")
    branch.mark(tab="shipping")
    assert branch.tab_for("order", "g1") == "shipping"
    assert branch.tab == "shipping", "the branch's own tab still says where the screen is"


def test_the_per_record_tabs_are_bounded_and_the_oldest_goes_first():
    branch = Branch(branch_id="br_1", session_id="s1")
    for i in range(progressive_max := 40):
        branch.mark(tab="orders", of=f"customer:cus_{i}")
    assert len(branch.tabs) <= Branch.MAX_TABS < progressive_max
    assert branch.tab_for("customer", f"cus_{progressive_max - 1}") == "orders", "the newest is kept"
    assert branch.tab_for("customer", "cus_0") == "", "the oldest was dropped"


def test_the_page_no_longer_hands_one_branch_tab_to_every_card():
    """The line the forensics names: `web/app.js:1692  tab: branchState && branchState.tab`.

    Read as source because there is no browser in this suite — the same discipline as
    tests/test_web.py, and for the same reason: this particular mistake is invisible until a
    tablet draws a second customer.
    """
    body = APP_JS[APP_JS.index("function renderOpts()"):]
    body = body[: body.index("\n}")]
    # The code, without the comments that are allowed to name the defect they fixed.
    code = "\n".join(line for line in body.splitlines() if not line.strip().startswith("//"))
    assert "branchState.tab" not in code, "a branch-wide tab is still being handed to every card"
    assert re.search(r"^\s+tab:", code, re.M) is None, "renderOpts still carries one tab for the whole branch"
    assert "tabOf:" in code, "cards are not told where to find their own record's tab"
    # And the renderer resolves it per card rather than taking one value for the deck.
    assert "function tabFor(" in UI_JS
    assert "initial: opts && opts.tab" not in UI_JS, "a card still opens on the deck-wide tab"
    assert UI_JS.count("initial: tabFor(") == 3, "every card with tabs resolves its own"


def test_a_spoken_request_for_a_part_of_a_record_is_that_records_tab():
    """"Show me the shipping on 1912" is a task that names a tab (§3/§12), and it reaches the
    card the same way a tap does — through `surface.tab`, filed against the RECORD.

    So the task-implied tab is not a new mechanism: the command layer already had it, and
    what was wrong was where it was kept. This is the end of that path, from the command to
    the map the tablet resolves a card's tab from.
    """
    from app import commands

    branch = Branch(branch_id="br_1", session_id="s1")
    branch.visit("order", "g1", "#1912")
    outcome = commands.run("surface.tab", commands.Ctx(None, None, branch, {"surface": "order", "tab": "shipping"}))
    assert outcome.ok, outcome.refusal
    assert branch.tab_for("order", "g1") == "shipping"
    assert branch.public()["tabs"] == {"order:g1": "shipping"}
    # And the order beside it on the same half is not moved to Shipping.
    assert branch.tab_for("order", "g2") == ""


def test_the_tab_a_task_implies_is_named_on_the_card_it_is_about():
    """The contract with the workspace composition (workstream B): the intended tab rides on
    the CARD, as `data.tab`, which `app/render.py` already treats as visual state — so naming
    it does not redraw the card, and a card nobody named opens on its own first panel."""
    from app.render import VISUAL_KEYS, fingerprint

    assert "tab" in VISUAL_KEYS
    plain = {"type": "customer", "data": {"customer_id": "c1", "name": "Ada"}}
    named = {"type": "customer", "data": {"customer_id": "c1", "name": "Ada", "tab": "orders"}}
    assert fingerprint(plain) == fingerprint(named), "the tab is how a card is drawn, not what it says"
    assert render_id(plain) == render_id(named)


# --------------------------------------------------------------------------- §15 the identity


def test_a_compound_task_says_what_the_workspace_is_before_any_fact_arrives():
    """§15. `turn_c8eb4cffe077` — "look up today's orders and today's emails and see if
    anything correlates" — put NOTHING on the glass for 7,975 ms. An invisible empty shell is
    not progress either: the workspace names itself and the sections that are coming.
    """
    clock = Clock()
    # The model's lane, which is where the compound questions live: the router has no family
    # for "orders and emails and see if anything correlates", and the READ PLAN is what knows
    # (app/reads/scheduler.py names the sections before it runs the first read).
    workspace = progressive.begin("s1", turn_id="t1", clock=clock)
    assert workspace.patches == [], "nothing is promised before anything is known"
    workspace.plan(kinds=("order_list", "email_list"))
    patches = workspace.patches
    assert patches, "nothing was staged at all"
    first = patches[0]
    assert first.type == "workspace_plan", f"the first thing on the glass was {first.type}"
    assert first.op == ADDED
    data = first.item["data"]
    assert data["title"], "the workspace has no name"
    assert [s["label"] for s in data["sections"]] == ["Orders", "Inbox"]
    assert {s["state"] for s in data["sections"]} <= {progressive.LOADING, progressive.WAITING}
    assert data["state"] == progressive.LOADING
    # A state is not a value: nothing on this card is a number the Mac has not read.
    assert all(not s.get("value") for s in data["sections"])
    assert workspace.timings()["time_to_visible_shell"] == 0.0
    assert workspace.timings()["time_to_first_meaningful_fact"] is None


def test_the_read_plan_is_what_names_the_sections_and_a_predicted_one_names_nothing():
    """The production call site: `app/reads/scheduler.py` hands the plan's tools over before
    it runs the first read of it, which is the earliest moment anything is known.

    And a read NOBODY ASKED FOR promises nothing. D-4 is what happens when anticipation is
    allowed to spend the foreground's room; a workspace header for a question the owner did
    not ask would be the same defect with a title on it.
    """
    class FakeSession:
        session_id = "s1"
        focused_branch = ""

    workspace = progressive.begin("s1", turn_id="t1")
    with progressive.background():
        progressive.planning(FakeSession(), ["shopify_list_orders", "gmail_search"])
    assert workspace.patches == [], "a predicted plan put a workspace on the glass"

    progressive.planning(FakeSession(), ["shopify_list_orders", "gmail_search", "gmail_read_thread"])
    plan = [p for p in workspace.patches if p.type == progressive.PLAN_TYPE]
    assert len(plan) == 1, [p.type for p in workspace.patches]
    # Two reads of one section are one section, and the order they were planned in is kept.
    assert [s["label"] for s in plan[0].item["data"]["sections"]] == ["Orders", "Inbox"]
    assert all(s["state"] == progressive.WAITING for s in plan[0].item["data"]["sections"])
    # A plan of one kind is not a workspace with a header over it.
    progressive.reset()
    alone = progressive.begin("s2", turn_id="t2")
    progressive.planning(FakeSession(), ["shopify_list_orders"])
    assert [p.type for p in alone.patches] == []


def test_a_section_is_patched_in_place_and_the_workspace_is_not_replaced():
    """§15's rules, as patches: patch sections in place, never replace the workspace, never
    duplicate a card, never reorder what is already there."""
    clock = Clock()
    workspace = progressive.begin("s1", turn_id="t1", clock=clock)
    workspace.plan("Today's activity", ("order_list", "email_list"))
    plan_id = workspace.patches[0].render_id

    clock.at(300)
    workspace.facts([orders(7)])
    clock.at(1100)
    workspace.facts([inbox(4)])

    plan = [p for p in workspace.patches if p.type == "workspace_plan"]
    assert [p.op for p in plan] == [ADDED, DATA, DATA], [p.op for p in plan]
    assert {p.render_id for p in plan} == {plan_id}, "the workspace was replaced instead of patched"
    sections = {s["name"]: s for s in plan[-1].item["data"]["sections"]}
    assert sections["orders"]["state"] == progressive.READY and sections["orders"]["value"] == "7"
    assert sections["inbox"]["state"] == progressive.READY and sections["inbox"]["value"] == "4"
    assert plan[-1].item["data"]["state"] == progressive.READY
    # And the cards themselves are one each, in the order they landed.
    assert workspace.ledger.order == [plan_id, "order_list:Today", "email_list:Email"]


def test_the_four_numbers_are_the_ones_section_fifteen_asks_for():
    """Phase 4's four, renamed to say what they measure. `time_to_shell` measured a shell
    that was not necessarily meaningful; §15 says that does not count, so the new
    `time_to_visible_shell` is the moment a shell with IDENTITY was on the glass."""
    assert progressive.TIMINGS == (
        "time_to_visible_shell", "time_to_first_meaningful_fact",
        "time_to_first_actionable_surface", "time_to_complete_workspace",
    )
    clock = Clock()
    workspace = progressive.begin("s1", turn_id="t1", clock=clock)
    workspace.plan("Today's activity", ("order_list", "email_list"))
    clock.at(300)
    workspace.facts([orders(7)])
    clock.at(1100)
    workspace.facts([inbox(4)])
    clock.at(7975)
    workspace.complete([orders(7), inbox(4), {"type": "assistant", "data": {"text": "Seven orders, four emails."}}])
    times = workspace.timings()
    assert set(times) == set(progressive.TIMINGS)
    assert times["time_to_visible_shell"] == 0.0
    assert times["time_to_first_meaningful_fact"] == 300.0
    assert times["time_to_first_actionable_surface"] == 300.0
    assert times["time_to_complete_workspace"] == 7975.0


def test_an_anonymous_skeleton_is_not_a_visible_shell():
    """The honest half of the rename. A bounded grey box that says "Reading…" and names
    nothing is not the moment the owner had a workspace, and it no longer claims to be."""
    clock = Clock()
    workspace = progressive.Workspace("s1", clock=clock)
    clock.at(20)
    workspace.facts([{"type": "inventory", "data": {"shell": True, "loading": True, "title": "Reading", "placeholder": 3}}])
    assert workspace.timings()["time_to_visible_shell"] is None, "an unnamed skeleton counted as a working screen"
    clock.at(40)
    workspace.plan("Stock", ("inventory",))
    assert workspace.timings()["time_to_visible_shell"] == 40.0


def test_a_named_section_shell_carries_identity_on_its_own():
    """One read, one card: the titled skeleton names the section, so the workspace identity
    is on the glass without a header card over a single card."""
    clock = Clock()
    workspace = progressive.begin("s1", turn_id="t1", clock=clock)
    workspace.starting("shopify_list_orders")
    assert [p.type for p in workspace.patches] == ["order_list"], "a one-section task got a header card"
    assert workspace.patches[0].item["data"]["title"] == "Orders"
    assert workspace.timings()["time_to_visible_shell"] == 0.0


# --------------------------------------------------------------------------- §27 the states


def test_every_state_a_section_can_be_in_is_one_of_five():
    assert progressive.STATES == ("loading", "partial", "ready", "empty", "error")
    assert progressive.WAITING == "waiting", "a read that has not started is not a state of the workspace"


def test_an_empty_read_keeps_the_workspace_and_is_not_an_error():
    """§27, in the words of the brief: EMPTY IS NOT ERROR. "No Gmail threads found" keeps the
    customer workspace and shows `Inbox — No messages found`; it must not replace the
    workspace with an empty email screen."""
    clock = Clock()
    workspace = progressive.begin("s1", turn_id="t1", clock=clock)
    workspace.plan("Today's activity", ("order_list", "email_list"))
    clock.at(300)
    workspace.facts([orders(7)])
    clock.at(800)
    workspace.facts([{"type": "email_list", "data": {"title": "Email", "count": 0, "threads": [], "empty": True, "note": "No messages found"}}])
    plan = [p for p in workspace.patches if p.type == "workspace_plan"][-1].item["data"]
    sections = {s["name"]: s for s in plan["sections"]}
    assert sections["inbox"]["state"] == progressive.EMPTY
    assert sections["inbox"]["state"] != progressive.ERROR
    assert sections["inbox"]["note"] == "No messages found"
    assert sections["orders"]["state"] == progressive.READY, "the section that landed is untouched"
    assert plan["state"] == progressive.READY, "a workspace with an empty section is still a workspace"
    # The workspace is still there, with every section on it.
    assert len(plan["sections"]) == 2


def test_a_workspace_whose_every_section_found_nothing_is_empty_and_not_an_error():
    clock = Clock()
    workspace = progressive.begin("s1", turn_id="t1", clock=clock)
    workspace.plan("Today's activity", ("order_list", "email_list"))
    workspace.facts([{"type": "order_list", "data": {"title": "Today", "count": 0, "orders": [], "empty": True, "note": "No orders yet"}}])
    workspace.facts([{"type": "email_list", "data": {"title": "Email", "count": 0, "threads": [], "empty": True, "note": "No messages found"}}])
    plan = [p for p in workspace.patches if p.type == "workspace_plan"][-1].item["data"]
    assert plan["state"] == progressive.EMPTY
    assert plan["state"] != progressive.ERROR


def test_an_error_in_one_section_does_not_destroy_the_others():
    """§27's last line. The inbox read failed; the orders that landed are still on the glass,
    still saying what they found, and the workspace is still usable."""
    clock = Clock()
    workspace = progressive.begin("s1", turn_id="t1", clock=clock)
    workspace.plan("Today's activity", ("order_list", "email_list"))
    clock.at(300)
    workspace.facts([orders(7)])
    clock.at(900)
    workspace.failed("gmail_search", "Gmail did not answer")
    plan = [p for p in workspace.patches if p.type == "workspace_plan"][-1].item["data"]
    sections = {s["name"]: s for s in plan["sections"]}
    assert sections["inbox"]["state"] == progressive.ERROR
    assert sections["inbox"]["note"] == "Gmail did not answer"
    assert sections["orders"]["state"] == progressive.READY and sections["orders"]["value"] == "7"
    assert plan["state"] == progressive.PARTIAL, "one failed section made the whole workspace an error"
    # The orders card itself was never taken down.
    assert "order_list:Today" in workspace.ledger.order


def test_a_failed_read_takes_down_its_own_skeleton_and_nothing_else():
    clock = Clock()
    workspace = progressive.begin("s1", turn_id="t1", clock=clock)
    workspace.plan("Today's activity", ("order_list", "email_list"))
    workspace.starting("gmail_search")
    assert workspace.ledger.has_real("order_list") is False
    clock.at(500)
    removed = [p for p in workspace.failed("gmail_search", "Gmail did not answer") if p.op == "remove"]
    assert [p.type for p in removed] == ["email_list"], "a skeleton was left reading for a read that failed"


def test_the_sections_still_being_read_are_the_ones_a_card_should_draw_as_loading():
    """The join with the workspace composition: WHEN a section is in flight is known here,
    WHAT goes in it is composed in app/presentation.py, and this is all that crosses.

    A section that has landed, found nothing, or failed is not in flight: it has an answer,
    and a card that drew it as "loading…" would be saying the Mac was still working when it
    had stopped — the live session's "Checking the inbox…" standing 34.8 s after the asking.
    """
    class FakeSession:
        session_id = "s1"
        focused_branch = ""

    workspace = progressive.begin("s1", turn_id="t1")
    workspace.plan("Today's activity", ("order_list", "email_list"))
    assert workspace.in_flight() == ["orders", "inbox"]
    assert progressive.in_flight(FakeSession()) == ["orders", "inbox"]
    workspace.facts([orders(7)])
    assert workspace.in_flight() == ["inbox"]
    workspace.failed("gmail_search", "Gmail did not answer")
    assert workspace.in_flight() == [], "a section that failed is not still being read"
    # And a session with no workspace at all says so rather than raising.
    progressive.reset()
    assert progressive.in_flight(FakeSession()) == []


def test_the_workspace_state_is_reported_with_the_turns_numbers():
    clock = Clock()
    workspace = progressive.begin("s1", turn_id="t1", clock=clock)
    workspace.plan("Today's activity", ("order_list", "email_list"))
    clock.at(200)
    workspace.facts([orders(7)])
    assert workspace.state == progressive.PARTIAL
    clock.at(400)
    workspace.facts([inbox(4)])
    assert workspace.state == progressive.READY
    assert workspace.public()["state"] == progressive.READY


# --------------------------------------------------------------------------- D-8


def test_one_turn_does_not_draw_the_same_surface_seven_times():
    """D-8. `turn_f0628fcf7be5` drew `order_list + working_set + folded` seven times — #2
    through #7 at 0.0 s apart, one at 2.5 s — and each redraw cost the scroll position while
    he was scrolling. The same three cards staged seven times are three cards."""
    clock = Clock()
    workspace = progressive.begin("s1", turn_id="t1", clock=clock)
    trio = [orders(3), {"type": "working_set", "data": {"set_id": "set_1", "label": "Today's orders", "total": 3}}]
    drawn = []
    for i in range(7):
        clock.at(100 * i)
        drawn.extend(workspace.facts([dict(card) for card in trio]))
    added = [p.render_id for p in drawn if p.op == ADDED]
    assert len(added) == len(set(added)) == 2, f"an identity was drawn from scratch twice: {added}"
    assert [p.op for p in drawn if p.op == DATA] == [], "the same card was redrawn with the same words"
    assert workspace.ledger.counts["suppressed"] == 12, workspace.ledger.report()
    # And the report says so, by identity, so a churning card is visible as a number.
    assert workspace.ledger.report()["suppressed:order_list"] == 6


def test_the_page_records_one_render_for_one_screen():
    """The tablet's half of D-8, read as source. Six of that turn's seven renders were at the
    same instant: the deck was drawn, snapshotted, and drawn again. A draw whose result is the
    screen that is already there is not a render, and it is not counted as one."""
    snap = APP_JS[APP_JS.index("function snapshotSoon(extra)"):]
    snap = snap[: snap.index("\n}")]
    assert "deckPrint" in snap, "nothing compares the screen with the one already recorded"
    assert "render_repeat" in snap, "a repeated draw is silently counted as another render"
    adopt = APP_JS[APP_JS.index("function adoptContext(nodes, items, question)"):]
    adopt = adopt[: adopt.index("\n}")]
    assert "snapshotSoon(" not in adopt, "one answer still takes two render snapshots"


# --------------------------------------------------------------------- the two sides agree


def test_the_workspace_plan_is_a_card_both_sides_know():
    from app.render import KEY_OF

    assert "workspace_plan" in UI_TYPES
    assert KEY_OF["workspace_plan"] == ("workspace_id",)
    renderers = set(re.findall(r"^\s{4}(\w+): render\w+,$", UI_JS, re.M))
    assert "workspace_plan" in renderers
    # It is the only card the Mac stages that `present()` never builds, so it is named here.
    assert progressive.PLAN_TYPE == "workspace_plan"


def test_both_sides_know_the_same_five_states():
    """§27's vocabulary is a contract, so it is held in both files and compared here: a state
    the Mac can send and the tablet has no word for would be drawn as the raw word, and one
    the tablet knows and the Mac never sends is a screen nobody can reach."""
    words = re.search(r"const PLAN_WORDS = \{([^}]*)\}", UI_JS)
    assert words, "the tablet has no words for the states"
    tablet = {part.split(":")[0].strip() for part in words.group(1).split(",") if ":" in part}
    assert tablet == set(progressive.STATES) | {progressive.WAITING}, tablet
    kickers = re.search(r"const PLAN_STATE = \{([^}]*)\}", UI_JS)
    assert kickers, "the tablet has no line for the workspace's own state"
    heads = {part.split(":")[0].strip() for part in kickers.group(1).split(",") if ":" in part}
    assert heads == set(progressive.STATES), heads


def test_every_planned_section_names_a_card_the_renderer_can_draw():
    renderers = set(re.findall(r"^\s{4}(\w+): render\w+,$", UI_JS, re.M))
    # A section is planned from the reads that are about to run (`progressive.planning`), so
    # every card a read can promise must have a section and a renderer.
    for tool, kind in progressive.SHELL_OF_TOOL.items():
        assert kind in progressive.SECTION_OF_KIND, f"{tool} plans {kind}, which has no section"
        assert kind in renderers, f"{tool} plans {kind}, which the tablet cannot draw"
    for kind in progressive.SECTION_OF_KIND:
        assert kind in UI_TYPES, f"{kind} has a section and is not in the vocabulary"


def test_a_count_on_a_section_counts_the_section_and_not_the_first_list_on_the_card():
    """`Orders · 3` must mean three orders. The first list on an ORDER card is its line
    items, so a count read from "the first list on the card" would have said three socks."""
    clock = Clock()
    workspace = progressive.begin("s1", turn_id="t1", clock=clock)
    workspace.facts([{"type": "order", "data": {"order_id": "g1", "order_number": "#1938", "detail": True,
                                                "items": [{"title": "Socks"}, {"title": "Hoodie"}, {"title": "Cap"}]}}])
    section = workspace.sections["orders"]
    assert section.state == progressive.READY
    assert section.value == "", "a card about one record was given a count of its contents"
    # A listing does carry one, and it is the listing's own.
    workspace.facts([inbox(4)])
    assert workspace.sections["inbox"].value == "4"


def test_every_read_that_draws_a_card_belongs_to_a_section():
    """A read whose card has no section would land on the glass without the workspace header
    ever saying it was coming."""
    for tool, kind in progressive.SHELL_OF_TOOL.items():
        assert kind in progressive.SECTION_OF_KIND, f"{tool} draws {kind}, which belongs to no section"


# --------------------------------------------------------------------- the tablet, under Node

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed here")


@needs_node
def test_the_tabs_and_the_states_under_node():
    """D-2, §15 and §27 on the glass: which tab a card opens on, and the five states.

    Run from here rather than from tests/test_web_js.py so that this pass's own node tests
    travel with this pass's own python tests.
    """
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "tabs.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_patching_in_place_still_holds_under_node():
    """The five rules Phase 4 established (tests/web/progressive.test.js) must still hold with
    a per-card tab and a workspace header in the mix: no reset scroll, no lost focus, no
    duplicate card."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "progressive.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout
