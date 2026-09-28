"""§13: a summary question gets a summary surface, and the tap on it goes somewhere.

D-4, from docs/phase5/LIVE_SESSION_FORENSICS.md, verbatim:

    turn_be1b384ca420   "Has anyone bought today that has bought before, a returning customer?"
    Answer, correctly: one.   Rendered: SEVEN full customer cards, 265 px each, 1,949 px.
    Tools: shopify_customer_history x 7 — one per candidate customer.

The generated report called this DUPLICATE_RENDER. It is not one: the seven ids (…6343,
…4807, …5015, …4055, …7975, …2855, …8887) are seven different people. Nothing was drawn
twice. The defect is that a question whose answer is a COUNT was answered with seven entity
profile pages.

So every test in this file asserts the SURFACE — how many cards, of which kind, carrying
which words — and never that the sentence was right. The sentence was right that evening.

The fixture is built to the shape of the real turn: seven buyers in the window, exactly ONE
of whom had bought before, with their previous order on 31 August so the row's "previous
order" line has a real date to carry.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import commands
from app.analytics.cache import OrderCache
from app.families import load_all
from app.memory import ENTITY
from app.memory import current as memory
from app.presentation import compact, present
from app.session.branch import Branch
from app.session.models import Session
from app.tools import analytics_tools
from tests.test_analytics import HOODIE, JEANS, JOGGERS, LONDON, NOW, node
from tests.test_analytics_tools import Store

load_all()

# The seven buyers of turn_be1b384ca420, by the last four digits the forensics kept, and in
# the same shape: seven different customers, one of whom has bought before.
SEVEN = (
    ("gid://shopify/Customer/5015", "Cy Cole", 2, 120.0),        # the returning one
    ("gid://shopify/Customer/6343", "Ann Able", 1, 45.0),
    ("gid://shopify/Customer/4807", "Ben Bold", 1, 90.0),
    ("gid://shopify/Customer/4055", "Di Dane", 1, 45.0),
    ("gid://shopify/Customer/7975", "Ed Eddy", 1, 45.0),
    ("gid://shopify/Customer/2855", "Flo Fry", 1, 70.0),
    ("gid://shopify/Customer/8887", "Gus Gee", 1, 90.0),
)
RETURNING_ID = SEVEN[0][0]

# Today's seven orders — spread across the hours since midnight so every one is inside
# "today" at the fixture clock (a Wednesday, 15:30 London).
_TODAY = [
    node(1962 + n, days_ago=(n + 1) * 0.05, items=[(*HOODIE, "Grey", "M", 1, 60.0)], customer=customer)
    for n, customer in enumerate(SEVEN)
]
# The returning customer's PREVIOUS order, on 31 August — nine days before the fixture clock.
_BEFORE = [node(1930, days_ago=9.0, items=[(*HOODIE, "Grey", "M", 1, 60.0)],
                customer=SEVEN[0], fulfillment="FULFILLED")]
# One old, unpaid order for the attention question, and one shipped with no tracking.
_ATTENTION = [
    node(1900, days_ago=20.0, items=[(*JEANS, "Blue", "M", 1, 90.0)],
         customer=("gid://shopify/Customer/1111", "Hal Hood", 1, 90.0), financial="PENDING"),
    node(1901, days_ago=6.0, items=[(*JOGGERS, "Black", "L", 1, 45.0)],
         customer=("gid://shopify/Customer/2222", "Ivy Ives", 1, 45.0)),
]
# Yesterday's two orders, for the listing question.
_YESTERDAY = [
    node(1955, days_ago=1.2, items=[(*JEANS, "Blue", "M", 1, 90.0)],
         customer=("gid://shopify/Customer/3333", "Jo Jones", 1, 90.0)),
    node(1956, days_ago=1.4, items=[(*JOGGERS, "Pink", "S", 1, 45.0)],
         customer=("gid://shopify/Customer/4444", "Kit King", 1, 45.0)),
]

NODES = _TODAY + _BEFORE + _ATTENTION + _YESTERDAY


class FixedDatetime(datetime):
    """The shop's clock, fixed where the fixtures were built."""

    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@pytest.fixture()
def shop(monkeypatch):
    """The read tools against the orders above, at the clock they were built at."""
    store = Store(NODES)
    cache = OrderCache(lambda: store, clock=lambda: NOW.timestamp())
    analytics_tools.bind(cache)
    monkeypatch.setattr(analytics_tools, "datetime", FixedDatetime)
    try:
        yield store
    finally:
        analytics_tools.bind(None)


async def answer_for(task: str, period: str = "today", session: Session | None = None, branch: Branch | None = None):
    """The summary read (`commerce_summary`), called as the model calls it, and the cards the
    turn draws from that call (app/presentation.py), compacted as the glass has them.

    Every summary question is the model's since 28 September 2026, when the word-matching
    lane that used to draw these was removed; the model's call of the read is what they are
    drawn from now.
    """
    session = session or Session(session_id="sum")
    session.turn_id = session.turn_id or "turn_sum"
    branch = branch or Branch(branch_id="br_sum", session_id=session.session_id)
    args = {"task": task, "limit": 12}
    if task != "orders_attention":
        args["period"] = period
    from app.tools.dispatch import dispatch

    # Through the dispatcher, as a read reaches any tool: it is what issues the ids a row's tap
    # is later checked against.
    calls: list = []
    await dispatch("commerce_summary", args, session=session, timeout_s=6.0, calls=calls)
    assert calls and calls[-1].ok, calls
    ui = compact(present(calls, session=session))
    drawn = [item for item in ui if item["type"] == "summary_list"]
    assert drawn, f"the model's read drew no summary card: {[i['type'] for i in ui]}"
    return drawn[0], ui, session, branch


def summaries():
    """The surface builders this pass adds. Imported here and not at the top of the file so
    that a tree without them fails on the assertion that describes the defect."""
    import app.summaries as module

    return module


def aggregation():
    from app.analytics import summarise

    return summarise


def kinds(ui) -> list[str]:
    return [item["type"] for item in ui if item["type"] != "context_stack"]


# A compact surface is one that carries ROWS. Two shapes do: the summary surface this pass
# adds (`rows`) and the order list the Mac already had (`orders`), which is compact and stays
# the surface for a listing the owner walks with a cursor. An entity PROFILE — `order`,
# `customer` — carries neither and is what a list question must never be answered with.
ROW_KEYS = ("rows", "orders", "customers", "threads")
PROFILE_KINDS = ("order", "customer", "product", "email_thread")


def row_bearing(ui) -> list[dict]:
    return [item for item in ui
            if item["type"] != "context_stack" and any(item["data"].get(k) for k in ROW_KEYS)]


def row_labels(item) -> list[str]:
    """What the rows say they are, whichever compact shape the surface is."""
    data = item["data"]
    if data.get("rows"):
        return [str(row.get("label") or "") for row in data["rows"]]
    return [str(row.get("order_number") or row.get("name") or "") for row in data.get("orders") or data.get("customers") or []]


# ------------------------------------------------ the defect: seven profiles for a count


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_compact_row_carries_what_the_brief_asks_for(shop):
    """The brief's own worked example:

        RETURNING CUSTOMERS TODAY · 1
        [name]
        Order #1962
        Previous order: Aug 31
        Lifetime: £120
        2 orders
    """
    _surface, ui, _session, _branch = await answer_for("returning_customers")
    data = ui[0]["data"]
    assert data["title"] == "Returning customers today" and data["count"] == 1
    (row,) = data["rows"]
    assert row["label"] == "Cy Cole"
    assert row["sub"] == "Order #1962", row
    lines = {line["label"]: line["value"] for line in row["lines"]}
    assert lines["Previous order"] == "31 Aug", lines
    assert lines["Lifetime"] == "£120.00", lines
    assert lines["Orders"] == "2", lines


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_attention_question_draws_attention_rows_not_a_days_listing(shop):
    """"Which orders need attention?" was answered with a plain period listing of every order
    of the day — the right card for a different question. It gets attention rows."""
    _surface, ui, _session, _branch = await answer_for("orders_attention")
    assert kinds(ui) == ["summary_list"], kinds(ui)
    data = ui[0]["data"]
    assert data["task"] == "orders_attention", data["task"]
    assert data["count"] >= 1 and data["rows"], data
    # The rows say what is wrong, in words, not just which orders exist.
    assert any("Waiting to go out" in row["sub"] or "Not paid" in row["sub"] for row in data["rows"]), data["rows"]
    # And the title does not claim a period nobody named.
    assert data["title"] == "Orders that need attention", data["title"]
    # The twenty-day-old unpaid order is in it, which is the point of the previous line: the
    # attention question is never narrowed to a day, even when the sentence carries one.
    assert "#1900" in [row["label"] for row in data["rows"]], data["rows"]


# --------------------------------------------------------------- §18: the tap resolves


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_compact_rows_tap_opens_the_real_customer_workspace(shop):
    """The row offers a tap, and the tap lands on workstream B's customer card.

    D-6 was the opposite: a control drawn, posted, and refused `not_held`, with an empty half
    underneath it. So this asserts the whole route — the row says it is tappable, the ref it
    carries passes the same check `open.entity` applies, and running that command produces a
    `customer` card and no refusal.
    """
    _surface, ui, session, branch = await answer_for("returning_customers")
    (row,) = ui[0]["data"]["rows"]
    assert row["tap"] is True and row["kind"] == "customer" and row["command"] == "open.entity"

    # The Mac holds this customer's record — which is what a tap on a row it has just drawn
    # can rely on, and what makes the tap free.
    memory().put(ENTITY, f"customer:{row['ref']}", {
        "customer_id": row["ref"], "name": "Cy Cole", "orders": 2, "spent": "120.00 GBP",
        "standing": "returning", "recent": [],
    }, source="shopify", query="test:summaries", provenance={"test": "summaries"})

    opened = commands.run("open.entity", commands.Ctx(
        runtime=None, session=session, branch=branch,
        args={"kind": row["kind"], "ref": row["ref"], "label": row["label"]},
    ))
    assert opened.ok, f"the tap was refused: {opened.code} {opened.detail}"
    drawn = present(list(opened.calls), session=session)
    assert "customer" in [item["type"] for item in drawn], [item["type"] for item in drawn]
    assert branch.entity == {"kind": "customer", "ref": row["ref"], "label": "Cy Cole"}, branch.entity


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_tap_the_mac_does_not_hold_reads_it_rather_than_refusing(shop):
    """Not holding the record is not a dead end: the outcome names the read the route makes.

    The distinction matters because it is the difference between D-6 and a working row. A row
    may offer a tap when the DESTINATION resolves; whether the Mac happens to have the record
    cached decides whether the tap costs a read, not whether it works.
    """
    _surface, ui, session, branch = await answer_for("returning_customers")
    (row,) = ui[0]["data"]["rows"]
    # Nothing is put in the entity cache for this ref: this is the cache-miss case.
    opened = commands.run("open.entity", commands.Ctx(
        runtime=None, session=session, branch=branch,
        args={"kind": "customer", "ref": row["ref"], "label": row["label"]},
    ))
    assert opened.ok, f"{opened.code}: {opened.detail}"
    assert opened.calls or opened.changed.get("needs_read"), opened.changed


async def test_the_order_to_customer_hop_resolves_even_on_a_replayed_card(shop):
    """The click-path audit: path 1 dead at step 4 of 8 — an order card with its Customer tab
    open offers no control that opens the customer.

    The renderer's half is in tests/web/ui.test.js. This is the half that decides whether the
    control is alive: `open.entity` refuses a ref this conversation was never shown, and a
    REPLAYED order card is rebuilt from the entity cache rather than from a tool result, so
    `_harvest_ids` never sees its customer id. Drawing the card is the showing.
    """
    from app.memory import ENTITY
    from app.memory import current as memory
    from app.presentation import present

    order_id = "gid://shopify/Order/1938"
    customer_id = "gid://shopify/Customer/7001"
    held = {
        "order_id": order_id, "order_number": "CROOKS-1938", "detail": True,
        "customer_id": customer_id, "customer_name": "Mia Jones",
        "customer_email": "mia@example.com", "total": "84.00 GBP",
        "fulfillment": "UNFULFILLED", "payment": "PAID", "items": [],
    }
    memory().put(ENTITY, f"order:{order_id}", held, source="shopify", query="test:hop",
                 provenance={"test": "hop"})
    memory().put(ENTITY, f"customer:{customer_id}", {
        "customer_id": customer_id, "name": "Mia Jones", "orders": 3, "spent": "410.00 GBP",
        "standing": "returning", "recent": [],
    }, source="shopify", query="test:hop", provenance={"test": "hop"})

    session = Session(session_id="hop")
    session.issue(order_id)          # the list that was tapped issued the ORDER and nothing else
    branch = Branch(branch_id="br_hop", session_id="hop")
    opened = commands.run("open.entity", commands.Ctx(
        runtime=None, session=session, branch=branch,
        args={"kind": "order", "ref": order_id, "label": "CROOKS-1938"},
    ))
    assert opened.ok, f"{opened.code}: {opened.detail}"
    drawn = present(list(opened.calls), session=session)
    assert "order" in [item["type"] for item in drawn], [item["type"] for item in drawn]

    # The card is on the glass and it names the customer, so the hop off it must work. The
    # behavioural assertion comes first because it holds on any tree: post what the
    # renderer's control posts and read what comes back.
    hop = commands.run("open.entity", commands.Ctx(
        runtime=None, session=session, branch=branch,
        args={"kind": "customer", "ref": customer_id, "label": "Mia Jones"},
    ))
    assert hop.ok, f"the hop from the order to its customer was refused: {hop.code} {hop.detail}"
    assert "customer" in [item["type"] for item in present(list(hop.calls), session=session)]
    # And the same question the builder asks before it draws a control at all (§18).
    assert summaries().destination_for(session, "customer", customer_id) == "open.entity", sorted(session.issued_ids)


def test_a_row_whose_destination_does_not_resolve_is_drawn_without_a_tap():
    """§18, stated as the builder's own rule.

    Three ways a destination fails, and all three draw a row that is not a button: an id this
    conversation was never shown, an id of the wrong shape, and a kind nothing can re-read.
    """
    session = Session(session_id="dest")
    session.issue("gid://shopify/Customer/5015")
    assert summaries().destination_for(session, "customer", "gid://shopify/Customer/5015") == "open.entity"
    assert summaries().destination_for(session, "customer", "gid://shopify/Customer/9999") == "", "never shown"
    assert summaries().destination_for(session, "customer", "5015") == "", "not an id of that kind"
    assert summaries().destination_for(session, "product", "gid://shopify/Product/1") == "", "nothing re-reads a product"

    built = summaries().summary(
        task="returning_customers", title="Returning customers today", count=2,
        count_label="returning customers", session=session,
        rows=[summaries().Row(label="Shown", ref="gid://shopify/Customer/5015", kind="customer"),
              summaries().Row(label="Never shown", ref="gid://shopify/Customer/9999", kind="customer")],
    )
    shown, hidden = built.data["rows"]
    assert shown["tap"] is True and shown["ref"] == "gid://shopify/Customer/5015"
    assert hidden["tap"] is False and "ref" not in hidden, hidden
    assert built.data["tappable"] == 1


# ------------------------------------------------------------------- §26: human language


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_no_compact_surface_ever_shows_an_id(shop):
    """No `gid://` in anything the owner can read, on any of the three surfaces.

    The row's `ref` is the one value that carries an id. It is how the tablet names a record
    back to the Mac — the tablet names ids only — and the renderer puts it in `data-ref` and
    never in text (tests/web/ui.test.js asserts that side). Everything else is checked here,
    key by key, by the same guard the builders run at build time.
    """
    for text, period in (("returning_customers", "today"), ("orders_attention", ""),
                         ("order_list", "yesterday")):
        _surface, ui, _session, _branch = await answer_for(text, period)
        assert row_bearing(ui), f"{text!r} drew no compact surface at all: {kinds(ui)}"
        for item in row_bearing(ui):
            if item["type"] == "summary_list":
                # The guard the builder itself runs: every key except the declared ref keys.
                summaries().assert_human(item)
            for row in item["data"].get("rows") or item["data"].get("orders") or []:
                readable = {k: v for k, v in row.items()
                            if not k.endswith("_id") and k not in ("ref", "kind", "command")}
                assert "gid://" not in str(readable), f"{text!r}: {readable}"
                # And something human to read on every row.
                assert row_labels(item), f"{text!r}: a row with nothing to read"


def test_a_nameless_customer_is_named_by_their_order_not_by_their_id():
    """The hostile case, and the reason `_human` returns nothing rather than tidying.

    A guest checkout or an imported customer with no display name used to leave the row
    labelled "—". Printing the tail of the gid instead would put "7975" on the glass as
    though it were a person's name. So: the order they placed names them.
    """
    found = {
        "count": 1, "currency": "GBP", "buyers": 1, "orders_in_window": 1, "guests": 0,
        "rows": [{
            "customer_id": "gid://shopify/Customer/7975", "name": "", "email": "",
            "order_number": "CROOKS-1962", "order_id": "gid://shopify/Order/1962",
            "previous_known": True, "previous_at": "2026-08-31T10:00:00+01:00",
            "lifetime_orders": 2, "lifetime_spent": 120.0, "currency": "GBP",
        }],
    }
    session = Session(session_id="nameless")
    built = summaries().returning_customers(found, session=session, period="today")
    (row,) = built.data["rows"]
    assert row["label"] == "Whoever placed #1962", row["label"]
    assert "7975" not in row["label"] and "gid://" not in row["label"]
    summaries().assert_human(built)


def test_the_builder_refuses_to_ship_an_id_in_a_display_field():
    """The guard, tested directly: a later change that adds a field and forgets `_human` is a
    crash in this suite rather than a gid on the glass."""
    with pytest.raises(summaries().NotHuman):
        summaries().Row(label="gid://shopify/Customer/5015").as_dict(Session(session_id="x"))
    with pytest.raises(summaries().NotHuman):
        summaries().summary(task="t", title="T", count=0, count_label="none", rows=[],
                subtitle="for gid://shopify/Customer/5015")
    with pytest.raises(summaries().NotHuman):
        summaries().assert_human({"data": {"rows": [{"label": "fine", "sub": "gid://shopify/Order/1"}]}})
    # And the one key that may carry one does not trip it.
    summaries().assert_human({"data": {"rows": [{"label": "fine", "ref": "gid://shopify/Order/1"}]}})


# -------------------------------------------------------------- the aggregation itself


def _rows():
    from app.analytics.cache import shape_order

    return [shape_order(n, read_at=NOW.timestamp()) for n in NODES]


def test_the_aggregation_finds_exactly_the_one_who_had_bought_before():
    """Seven buyers, one returning — measured from the order rows the Mac already holds, with
    no per-customer read anywhere in it."""
    window = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    found = aggregation().returning_customers(
        _rows(), start=window.timestamp(), end=NOW.timestamp(), zone=LONDON,
    )
    assert found["count"] == 1 and found["buyers"] == 7, found
    (row,) = found["rows"]
    assert row["customer_id"] == RETURNING_ID
    assert row["order_number"] == "CROOKS-1962"
    assert row["previous_order_number"] == "CROOKS-1930" and row["previous_known"] is True
    assert row["previous_at"].startswith("2026-08-31"), row["previous_at"]
    assert row["lifetime_orders"] == 2 and row["lifetime_spent"] == 120.0


def test_a_customer_whose_previous_order_is_outside_the_window_says_so():
    """The honest end of it. The cache holds ninety days; a customer who last bought in March
    is returning — Shopify's own lifetime count says so — and the row does not invent a date
    or spend a read to find one."""
    lone = [node(1970, days_ago=0.1, items=[(*JEANS, "Blue", "M", 1, 90.0)],
                 customer=("gid://shopify/Customer/6060", "Lou Lane", 4, 400.0))]
    from app.analytics.cache import shape_order

    rows = [shape_order(n, read_at=NOW.timestamp()) for n in lone]
    window = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    found = aggregation().returning_customers(rows, start=window.timestamp(), end=NOW.timestamp(), zone=LONDON)
    (row,) = found["rows"]
    assert row["previous_known"] is False and row["previous_at"] == ""
    assert row["lifetime_orders"] == 4

    built = summaries().returning_customers(found, session=Session(session_id="lone"), period="today")
    lines = {line["label"]: line["value"] for line in built.data["rows"][0]["lines"]}
    assert lines["Previous order"] == "before the server's window", lines


def test_a_cancelled_order_is_not_a_purchase():
    """"Anyone bought today" must not come back yes on a checkout that was undone."""
    cancelled = [node(1971, days_ago=0.1, items=[(*JEANS, "Blue", "M", 1, 90.0)],
                      customer=SEVEN[0], cancelled=True)]
    from app.analytics.cache import shape_order

    rows = [shape_order(n, read_at=NOW.timestamp()) for n in cancelled]
    window = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    found = aggregation().returning_customers(rows, start=window.timestamp(), end=NOW.timestamp(), zone=LONDON)
    assert found["count"] == 0 and found["buyers"] == 0, found


def test_attention_is_read_from_the_row_and_ranks_the_worst_first():
    """Every fact on an attention row is already on the cache row, which is why the answer
    costs no per-order read. Unpaid outranks waiting; waiting long outranks waiting."""
    found = aggregation().orders_needing_attention(_rows(), now=NOW.timestamp(), zone=LONDON)
    numbers = [row["order_number"] for row in found["rows"]]
    assert numbers[0] == "CROOKS-1900", numbers
    assert found["rows"][0]["level"] == "red" and "Not paid for" in found["rows"][0]["headline"]
    assert found["red"] >= 1 and found["count"] == len(found["rows"])
    levels = [row["level"] for row in found["rows"]]
    assert levels == sorted(levels, key=lambda level: 0 if level == "red" else 1), levels


def test_lifetime_metrics_for_several_customers_at_once_read_nothing():
    """§14's second named workflow: the values are on the rows, so N reads become none."""
    held = aggregation().customer_lifetime(_rows(), [c[0] for c in SEVEN] + ["gid://shopify/Customer/404"], zone=LONDON)
    assert held[RETURNING_ID]["lifetime_orders"] == 2
    assert held[RETURNING_ID]["first_order_number"] == "CROOKS-1930"
    assert held[RETURNING_ID]["last_order_number"] == "CROOKS-1962"
    assert held["gid://shopify/Customer/404"] == {"held": False}, "never guessed at"


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_an_empty_answer_is_a_card_in_the_right_sentence(shop):
    """D-15 and §13 together. "Nothing needs attention" is not "no orders" — there were nine
    orders — so the empty sentence is the Mac's, per task, and reaches the surface."""
    # A day with orders, none of them from a returning buyer: yesterday's two are both first
    # orders, so the same question asked of yesterday finds nobody.
    _surface, ui, _session, _branch = await answer_for("returning_customers", "yesterday")
    data = ui[0]["data"]
    assert data["count"] == 0 and data["empty"] is True, data
    assert data["empty_words"] == "Nobody who bought yesterday had bought before.", data["empty_words"]
    assert data["title"] == "Returning customers yesterday", data["title"]


def test_a_summary_is_bounded_and_tells_the_truth_about_the_count():
    """Twenty-five matches on a twelve-row surface: the rows are capped, the count is not."""
    many = [node(2000 + n, days_ago=0.1 + n * 0.01, items=[(*JOGGERS, "Black", "L", 1, 45.0)],
                 customer=(f"gid://shopify/Customer/{9000 + n}", f"Buyer {n}", 3, 300.0))
            for n in range(25)]
    from app.analytics.cache import shape_order

    rows = [shape_order(n, read_at=NOW.timestamp()) for n in many]
    window = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    found = aggregation().returning_customers(rows, start=window.timestamp(), end=NOW.timestamp(),
                                          zone=LONDON, limit=12)
    assert found["count"] == 25 and len(found["rows"]) == 12 and found["truncated"] is True
    built = summaries().returning_customers(found, session=Session(session_id="many"), period="today")
    assert built.data["count"] == 25 and len(built.data["rows"]) == 12
    assert built.data["truncated"] is True


def test_the_period_the_summary_reports_is_the_period_it_was_asked_for():
    """A window is the caller's, never a guess: an order placed a minute before midnight is
    yesterday's, and "today" does not quietly widen to catch it."""
    zone = ZoneInfo("Europe/London")
    midnight = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    edge = [node(1980, days_ago=0.0, items=[(*JEANS, "Blue", "M", 1, 90.0)], customer=SEVEN[1])]
    from app.analytics.cache import shape_order

    rows = [shape_order(n, read_at=NOW.timestamp()) for n in edge]
    rows[0]["ts"] = (midnight - timedelta(minutes=1)).timestamp()
    today = aggregation().order_rows(rows, start=midnight.timestamp(), end=NOW.timestamp(),
                                 now=NOW.timestamp(), zone=zone)
    assert today["count"] == 0, today
    before = aggregation().order_rows(rows, start=(midnight - timedelta(days=1)).timestamp(),
                                  end=midnight.timestamp(), now=NOW.timestamp(), zone=zone)
    assert before["count"] == 1, before


# -------------------------------------------------------------------- read-only, always


def test_the_read_tool_is_a_read_and_the_scheduler_would_take_it():
    """`assert_reads_only` is the structural guarantee: a plan naming a write never runs."""
    from app.reads.scheduler import Read, ReadPlan, assert_reads_only

    assert_reads_only(ReadPlan([Read("summary", "commerce_summary", {"task": "order_list"})]))
    from app.tools import registry

    spec = registry.get("commerce_summary")
    assert spec.write is None and spec.batch is None
