"""The workspace that arrives in pieces, and the card that is only drawn once.

Every test here is one of the four defects the live session left behind:

* **D-5** nothing appeared until everything was ready. `turn_c8eb4cffe077` took 7,975 ms to
  first cards. The tests assert ORDERING AND TIMING — that a useful card exists well before
  the final one — not merely that the end state is right, because the end state always was.
* **D-13** 24 `email_thread` renders and five identical `order` renders across 14 turns. The
  tests assert that the repeat is suppressed and that the suppression is COUNTED.
* **D-15** a turn produced records with no card. The tests assert that a read which returned
  rows, and a read which returned none, both produce a card the renderer can draw.
* **§25** DATA UPDATED, VISUAL STATE UPDATED and NO VISIBLE CHANGE are three different things.

Phase 5 renamed the four glass timings this file asserts on (§15, app/progressive.py): a shell
that named nothing used to set `time_to_shell`, and §15 says an invisible empty shell is not
progress — so it is `time_to_visible_shell` now and only a shell with IDENTITY sets it.
`time_to_first_fact` and `time_to_first_useful_workspace` mean exactly what they meant and are
called `time_to_first_meaningful_fact` and `time_to_first_actionable_surface`. Nothing about
what these tests prove has been weakened; the keys say what they measure.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import progressive
from app.presentation import UI_TYPES, present
from app.providers.base import ToolCall
from app.render import DATA, REMOVED, VISUAL, RenderLedger, fingerprint, render_id

WEB = Path(__file__).resolve().parent.parent / "web"
UI_JS = (WEB / "ui.js").read_text(encoding="utf-8")
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_live_workspaces():
    progressive.reset()
    yield
    progressive.reset()


class Clock:
    """A clock a test drives. Seconds, because `perf_counter` is seconds."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def at(self, ms: float) -> None:
        self.t = ms / 1000.0


def order_card(number: str = "#1938", order_id: str = "gid://shopify/Order/1", **extra) -> dict:
    return {"type": "order", "data": {"order_id": order_id, "order_number": number, "detail": True, **extra}}


def thread_card(thread_id: str = "t1", subject: str = "Where is my order?", **extra) -> dict:
    return {"type": "email_thread", "data": {"thread_id": thread_id, "subject": subject, "messages": [], **extra}}


# --------------------------------------------------------------------------- render identity


def test_one_order_is_one_card_however_it_was_drawn():
    """The same record, found by a list, opened by a tap and enriched afterwards, is one
    identity. This is what makes patching in place possible at all."""
    found = {"type": "order", "data": {"order_id": "gid://shopify/Order/1", "order_number": "#1938", "detail": False}}
    opened = order_card()
    enriched = order_card(history={"orders": 4})
    assert render_id(found) == render_id(opened) == render_id(enriched)
    assert render_id(opened) != render_id(order_card("#1939", "gid://shopify/Order/2"))


def test_identity_survives_a_number_without_a_gid():
    """A read that returned only the number still names the same card as one that returned
    the gid — the order id is preferred, and the number is the fallback, not a second card."""
    assert render_id({"type": "order", "data": {"order_number": "#1938"}}) == "order:#1938"
    assert render_id({"type": "order", "data": {"order_id": "g1", "order_number": "#1938"}}) == "order:g1"


def test_a_card_about_no_record_is_identified_by_its_kind():
    assert render_id({"type": "assistant", "data": {"text": "hello"}}) == "assistant"
    assert render_id({"type": "error", "data": {"service": "gmail", "kind": "tool_failed"}}) == "error:gmail"


# --------------------------------------------------------------------------- patch semantics


def test_the_same_card_twice_is_drawn_once_and_the_repeat_is_counted():
    """D-13, as a number. Five identical order renders become one render and four suppressed."""
    ledger = RenderLedger()
    assert [p.op for p in ledger.stage([order_card()])] == ["add"]
    for _ in range(4):
        assert ledger.stage([order_card()]) == []
    assert ledger.counts["drawn"] == 1
    assert ledger.counts["suppressed"] == 4
    assert ledger.report()["suppressed:order"] == 4


def test_twenty_four_thread_renders_become_one_card_and_twenty_three_suppressions():
    ledger = RenderLedger()
    for _ in range(24):
        ledger.stage([thread_card()])
    assert ledger.counts["drawn"] == 1 and ledger.counts["suppressed"] == 23


def test_data_updated_visual_state_updated_and_no_visible_change_are_three_things():
    ledger = RenderLedger()
    ledger.stage([order_card()])
    # The customer's history landed: the card SAYS something new.
    assert [p.op for p in ledger.stage([order_card(history={"orders": 4})])] == [DATA]
    # It was folded behind a title: the same words, drawn differently.
    assert [p.op for p in ledger.stage([order_card(history={"orders": 4}, secondary=True)])] == [VISUAL]
    # And nothing at all.
    assert ledger.stage([order_card(history={"orders": 4}, secondary=True)]) == []
    assert ledger.counts["data"] == 1 and ledger.counts["visual"] == 1 and ledger.counts["suppressed"] == 1


def test_a_pending_region_settling_is_not_a_redraw():
    """`pending` says the Mac is still reading a region. Its going away is a mark on a tab,
    not a reason to rebuild the card the owner is reading."""
    ledger = RenderLedger()
    ledger.stage([order_card(pending=["history", "email"])])
    assert [p.op for p in ledger.stage([order_card(pending=[])])] == [VISUAL]


def test_the_fingerprint_ignores_only_how_a_card_is_drawn():
    plain = order_card()
    folded = order_card(secondary=True)
    assert fingerprint(plain) == fingerprint(folded)
    assert fingerprint(plain) != fingerprint(order_card(total="£84.00"))


# --------------------------------------------------------------------------- the shell


def test_the_shell_is_up_before_anything_has_been_read():
    clock = Clock()
    workspace = progressive.Workspace("s1", clock=clock)
    patches = workspace.shell(("order_list", "email_list"))
    # Changed in Phase 5 (§15): the FIRST thing on the glass is the workspace's identity —
    # what this screen is and the two sections coming — and then the skeletons of the cards
    # themselves. Phase 4 put up the skeletons alone, which is the "invisible empty shell"
    # §15 says does not count as progress.
    assert [p.type for p in patches] == ["workspace_plan", "order_list", "email_list"]
    assert [s["label"] for s in patches[0].item["data"]["sections"]] == ["Orders", "Inbox"]
    assert all(p.item["data"]["shell"] is True for p in patches[1:])
    assert workspace.timings()["time_to_visible_shell"] == 0.0
    # A skeleton says what kind of thing is coming and nothing else.
    assert set(patches[1].item["data"]) == {"shell", "loading", "title", "placeholder"}


def test_a_read_landing_takes_its_skeletons_place_rather_than_appearing_below_it():
    clock = Clock()
    workspace = progressive.Workspace("s1", clock=clock)
    workspace.shell(("order",))
    clock.at(120)
    patches = workspace.facts([order_card()])
    assert len(patches) == 1
    assert patches[0].op == "add"
    assert patches[0].replaces == "order:~shell", "the real card replaces the skeleton in place"
    # And the workspace now holds one order card, not a skeleton and an order.
    assert workspace.ledger.order == ["order:gid://shopify/Order/1"]


def test_a_skeleton_whose_read_never_landed_is_taken_down():
    """The live session left "Checking the inbox…" standing 34.8 s after the asking stopped.
    A shell that was never filled is removed when the turn ends, never left reading."""
    clock = Clock()
    workspace = progressive.Workspace("s1", clock=clock)
    workspace.shell(("order_list", "email_list"))
    clock.at(200)
    workspace.facts([{"type": "order_list", "data": {"title": "Today", "orders": [{"order_number": "#1938"}], "count": 1}}])
    clock.at(900)
    ops = workspace.complete([{"type": "order_list", "data": {"title": "Today", "orders": [{"order_number": "#1938"}], "count": 1}}])
    assert [(p.op, p.type) for p in ops if p.op == REMOVED] == [(REMOVED, "email_list")]


def test_a_started_read_puts_its_own_skeleton_up_when_the_family_did_not_know():
    clock = Clock()
    workspace = progressive.Workspace("s1", clock=clock)
    clock.at(40)
    assert [p.type for p in workspace.starting("gmail_search")] == ["email_list"]
    assert workspace.timings()["time_to_visible_shell"] == 40.0
    # The second read of the same kind does not stack a second skeleton.
    assert workspace.starting("gmail_search") == []
    # A tool whose card the Mac cannot predict promises nothing rather than promising wrong.
    assert workspace.starting("commerce_aggregate") == []


# --------------------------------------------------------------------------- D-5, measured


def test_a_useful_card_exists_well_before_the_final_one():
    """D-5. Orders land at 300 ms, the inbox at 1,100 ms, the correlation and the sentence at
    7,900 ms. The owner must be able to READ the orders at 300 ms — and the assertion is on
    the ordering and the timing, not on the end state, which was never the bug."""
    clock = Clock()
    workspace = progressive.begin("s1", turn_id="t1", clock=clock)
    # The model's first read goes out at once, and names what the screen is about to hold.
    workspace.starting("shopify_list_orders")
    assert workspace.timings()["time_to_visible_shell"] == 0.0

    clock.at(300)
    orders = {"type": "order_list", "data": {"title": "Today", "count": 3, "orders": [{"order_number": "#1938"}]}}
    first = workspace.facts([orders])
    assert [p.op for p in first] == ["add"]
    assert workspace.timings()["time_to_first_actionable_surface"] == 300.0

    clock.at(1100)
    mail = {"type": "email_list", "data": {"title": "Email", "count": 2, "threads": [{"thread_id": "t1", "subject": "Where is it?"}]}}
    assert [p.op for p in workspace.facts([mail])] == ["add"]

    clock.at(7975)
    final = workspace.complete([orders, mail, {"type": "assistant", "data": {"text": "Three orders, two emails."}}])
    times = workspace.timings()
    assert times["time_to_complete_workspace"] == 7975.0
    # The number the brief asks for: the screen was useful 7.6 seconds before it was finished.
    assert times["time_to_first_actionable_surface"] < times["time_to_complete_workspace"] / 4
    # And the two cards that were already right were NOT redrawn at the end.
    assert [p.op for p in final] == ["add"], "only the assistant's sentence was new"
    assert workspace.ledger.counts["suppressed"] == 2


def test_the_first_meaningful_fact_and_the_first_actionable_surface_are_not_the_same_moment():
    """An error card is a fact about the world and not a workspace. Keeping them apart is
    what stops "we drew something" being reported as "he could use it"."""
    clock = Clock()
    workspace = progressive.Workspace("s1", clock=clock)
    clock.at(80)
    workspace.facts([{"type": "error", "data": {"service": "gmail", "kind": "tool_failed", "title": "Email unavailable"}}])
    assert workspace.timings()["time_to_first_meaningful_fact"] == 80.0
    assert workspace.timings()["time_to_first_actionable_surface"] is None
    # And an error is not IDENTITY either: a screen carrying only "Email unavailable" does not
    # say what workspace this is, so §15's first number is still unanswered.
    assert workspace.timings()["time_to_visible_shell"] is None
    clock.at(400)
    workspace.facts([order_card()])
    assert workspace.timings()["time_to_first_actionable_surface"] == 400.0


def test_the_patch_log_is_bounded_and_a_tablet_can_catch_up_from_a_cursor():
    clock = Clock()
    workspace = progressive.Workspace("s1", clock=clock)
    workspace.shell(("order_list",))
    seen = workspace.public()
    assert seen["patches"] and seen["revision"] == seen["patches"][-1]["seq"]
    # Nothing new since: the poll is told so and the tablet draws nothing.
    assert workspace.public(since=seen["revision"])["patches"] == []
    clock.at(500)
    workspace.facts([order_card()])
    late = workspace.public(since=seen["revision"])
    assert [p["op"] for p in late["patches"]] == ["add"]
    assert late["patches"][0]["at_ms"] == 500.0


def test_a_read_nobody_asked_for_puts_nothing_on_the_glass():
    """D-4's lesson, applied here: anticipation may read, and it may not draw. A predicted
    plan's results are staged nowhere — the owner is looking at something else, and a card
    appearing under his hand for a question he did not ask is worse than a slow one."""
    class FakeSession:
        session_id = "s1"
        focused_branch = ""

    workspace = progressive.begin("s1")
    with progressive.background():
        progressive.starting(FakeSession(), "gmail_search")
        progressive.observe(FakeSession(), "gmail_search", {"threads": [{"thread_id": "t1", "subject": "Hi"}], "count": 1})
    assert workspace.patches == []
    # And the same calls in the foreground do reach it.
    progressive.observe(FakeSession(), "gmail_search", {"threads": [{"thread_id": "t1", "subject": "Hi"}], "count": 1})
    assert [p.type for p in workspace.patches] == ["email_list"]


def test_the_live_registry_is_bounded_and_per_half():
    for i in range(progressive.MAX_LIVE + 6):
        progressive.begin(f"s{i}")
    assert len(progressive._LIVE) == progressive.MAX_LIVE
    left = progressive.begin("split", branch_id="br_left")
    right = progressive.begin("split", branch_id="br_right")
    assert progressive.current("split", "br_left") is left
    assert progressive.current("split", "br_right") is right
    # With two halves in flight and no half named, nothing is guessed at.
    assert progressive.current("split") is None


# --------------------------------------------------------------------------- the two sides agree


def test_every_shell_promises_a_card_the_renderer_can_draw():
    renderers = set(re.findall(r"^\s{4}(\w+): render\w+,$", UI_JS, re.M))
    for tool, kind in progressive.SHELL_OF_TOOL.items():
        assert kind in UI_TYPES, f"{tool} promises {kind}, which the Mac cannot send"
        assert kind in renderers, f"{tool} promises {kind}, which the tablet cannot draw"
        assert kind in progressive.SHELL_WORDS, f"{tool} promises {kind} with no words"


def test_the_two_sides_name_the_same_cards_the_same_way():
    """Render identity is a contract, so it is held in both files and compared here.

    The Mac names a patch and the tablet has to find the node it is about. A table that drifts
    would not fail loudly — it would put a second card on the glass, which is the defect
    (D-13) rather than a symptom of one.
    """
    from app.render import KEY_OF as MAC

    block = UI_JS[UI_JS.index("const KEY_OF = {"):]
    block = block[: block.index("\n  };")]
    tablet = {}
    for line in block.splitlines()[1:]:
        line = line.strip().rstrip(",")
        if not line or ":" not in line:
            continue
        name, keys = line.split(":", 1)
        tablet[name.strip()] = tuple(k.strip().strip("'\"") for k in keys.strip().strip("[]").split(",") if k.strip())
    assert tablet == MAC, "the render-identity tables disagree"
    # And the shell suffix, which is how a skeleton hands its place over.
    from app.render import SHELL_SUFFIX

    assert f"const SHELL_SUFFIX = '{SHELL_SUFFIX}';" in UI_JS


def test_the_tablet_is_told_how_to_find_every_card_it_can_draw():
    """A type the tablet renders and the identity table does not name is identified by its
    kind alone — which is correct for the assistant's sentence and wrong for a record. Every
    type that carries a record must be in the table."""
    renderers = set(re.findall(r"^\s{4}(\w+): render\w+,$", UI_JS, re.M))
    from app.render import KEY_OF

    recordless = {"assistant", "attention", "inventory", "capability", "working_set"}
    for kind in sorted(renderers - set(KEY_OF) - recordless):
        raise AssertionError(f"{kind} has no render identity rule; two of them would be two cards")


def test_the_renderer_draws_a_skeleton_for_any_card_that_says_it_is_one():
    """No skeleton TYPE: a shell is an ordinary card whose data says `shell`. That is what
    keeps the vocabulary in step — there is nothing new in it to keep in step."""
    assert "skeletonCard" in UI_JS
    assert "data.shell === true" in UI_JS or "d.shell === true" in UI_JS


# --------------------------------------------------------------------------- the page's side
#
# There is no browser in this suite (the renderer is exercised under Node, and the pixels are
# measured in Chromium by tests/test_density.py), so these read the page as source — the same
# discipline as tests/test_web.py, and for the same reason: these particular mistakes would
# otherwise only be found on the tablet.


def test_the_poll_carries_a_cursor_and_asks_for_nothing_it_has_seen():
    assert "?since=${encodeURIComponent(String(glass.cursor))}" in APP_JS
    assert "if (data.workspace) applyWorkspace(data.workspace);" in APP_JS


def test_a_patch_is_never_applied_over_a_hand_on_the_glass():
    body = APP_JS[APP_JS.index("function applyWorkspace(payload)"):]
    body = body[: body.index("\n}")]
    assert "held: deckHeld" in body, "the batch must be offered the hold guard"
    # And the cursor is NOT advanced when the batch was deferred, so the next poll offers the
    # same patches again rather than the glass silently missing them.
    assert body.index("if (out.deferred)") < body.index("glass.cursor = Math.max")


def test_the_answer_reconciles_against_the_glass_before_it_redraws_it():
    body = APP_JS[APP_JS.index("function renderTurn(data)"):]
    body = body[: body.index("\n}")]
    assert body.index("adoptWorkspace(data)") < body.index("pushContext(ui.nodes")
    # adoptContext keeps the nodes that are already there; pushContext clears and appends.
    adopt = APP_JS[APP_JS.index("function adoptContext(nodes, items, question)"):]
    adopt = adopt[: adopt.index("\n}")]
    assert "showHistory(history.length - 1, { keep: true })" in adopt
    assert "clear(el.cards)" not in adopt


def test_every_way_a_turn_can_fail_takes_its_skeletons_down():
    submit = APP_JS[APP_JS.index("async function submit(body, isAudio)"):]
    submit = submit[: submit.index("\n}\n\nfunction sendAudio")]
    assert submit.count("settleGlass(") == 3, "a failed, a timed-out and an abandoned turn"


# --------------------------------------------------------------------------- D-15


def test_a_read_that_found_nothing_still_draws_a_card():
    """D-15. `turn_69abe877ef14` read the orders, found none, and drew NOTHING — the report
    counted it as "(records without a card)" and the owner saw an empty screen under a
    sentence. A read that returned no rows is an answer and gets a card that says so."""
    items = present([ToolCall(name="shopify_list_orders", args={}, ok=True,
                              result={"orders": [], "count": 0, "days": 1, "days_ago": 1})])
    assert [i["type"] for i in items] == ["order_list"]
    card = items[0]["data"]
    assert card["count"] == 0 and card["empty"] is True
    assert card["title"] == "Yesterday"
    assert card["note"], "the card says what was looked for and found none of"
    assert items[0]["type"] in UI_TYPES


def test_an_empty_inbox_read_draws_a_card_too():
    items = present([ToolCall(name="gmail_search", args={}, ok=True,
                              result={"threads": [], "count": 0, "query": "newer_than:1d"})])
    assert [i["type"] for i in items] == ["email_list"]
    assert items[0]["data"]["empty"] is True and items[0]["data"]["note"]


def test_no_read_result_with_records_in_it_can_produce_no_card():
    """The shape the report's "(records without a card)" bucket is looking for: a successful
    read whose payload carries rows. Every one of them draws something drawable."""
    results = {
        "shopify_list_orders": {"orders": [{"order_id": "g1", "order_number": "#1938"}], "count": 1},
        "shopify_find_order": {"orders": [{"order_id": "g1", "order_number": "#1938"}], "query": "1938"},
        "gmail_search": {"threads": [{"thread_id": "t1", "subject": "Hello"}], "count": 1},
        "shopify_find_customer": {"customers": [{"customer_id": "c1", "name": "A Customer"}]},
        "shopify_inventory": {"products": [{"product_id": "p1", "title": "Hoodie", "variants": []}]},
        "shopify_product_info": {"products": [{"product_id": "p1", "title": "Hoodie"}]},
    }
    for name, payload in results.items():
        items = present([ToolCall(name=name, args={}, ok=True, result=payload)])
        assert items, f"{name} returned records and drew no card"
        for item in items:
            assert item["type"] in UI_TYPES, f"{name} drew {item['type']}, which is not in the vocabulary"


def test_an_empty_card_never_sits_above_the_card_that_is_the_answer():
    """"No orders matched 1938" is the answer when it is all the turn found, and noise above
    the note being staged on the order a wider lookup missed. So the empties go where the turn
    produced anything substantive — this is the rule that keeps D-15's card from becoming its
    own defect."""
    from app.presentation import compact

    missed = ToolCall(name="shopify_find_order", args={}, ok=True, result={"orders": [], "query": "1938"})
    found = ToolCall(name="shopify_order_detail", args={}, ok=True,
                     result={"order_id": "g1", "order_number": "#1938", "items": []})
    items = present([missed, found])
    assert [i["type"] for i in items] == ["order"], items
    # And once more over the whole screen, where the answer is a recipe's own card.
    mixed = compact([
        {"type": "order_list", "data": {"title": "Orders", "count": 0, "empty": True, "note": "none", "orders": []}},
        {"type": "workspace", "data": {"workspace_id": "w1", "title": "A discount code"}},
    ])
    assert [i["type"] for i in mixed] == ["workspace"]


def test_a_card_the_tablet_cannot_draw_is_dropped_loudly(caplog, monkeypatch):
    """It has always been dropped. Dropping it SILENTLY is how a turn could produce "records
    without a card" and leave nothing to read afterwards — so the Mac names the type and says
    where the two sides of the vocabulary are kept."""
    import app.presentation as presentation

    monkeypatch.setattr(presentation, "_from_result", lambda name, result: [{"type": "hologram", "data": {"x": 1}}])
    with caplog.at_level("WARNING", logger="crooks.presentation"):
        items = present([ToolCall(name="shopify_list_orders", args={}, ok=True, result={"orders": []})])
    assert items == [], "a type outside the vocabulary never reaches the tablet"
    assert any("hologram" in record.message for record in caplog.records), caplog.text


def test_an_empty_read_of_every_listing_kind_draws_a_card():
    empties = {
        "shopify_list_orders": {"orders": [], "count": 0},
        "gmail_search": {"threads": [], "count": 0, "query": "in:inbox"},
        "shopify_find_customer": {"customers": [], "query": "nobody"},
        "shopify_inventory": {"products": [], "product": "nothing"},
        "shopify_product_info": {"products": [], "product": "nothing"},
    }
    for name, payload in empties.items():
        items = present([ToolCall(name=name, args={}, ok=True, result=payload)])
        assert items, f"{name} read and found nothing, and said nothing on the screen"
        assert all(i["type"] in UI_TYPES for i in items)
