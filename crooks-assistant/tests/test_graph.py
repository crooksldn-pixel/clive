"""The customer / order / email graph, in both directions, and what hangs off it.

Order → threads is `app/context/order.py`'s correlation, run by the hydrator. Thread → order
is `app/context/graph.py`, run by the presenter over the order cache. Neither may guess: every
link carries a confidence and the reasons, and a name is never one of them.
"""

from __future__ import annotations

import time

import pytest

from app.context import graph
from app.presentation import present
from app.providers.base import ToolCall
from app.session.models import Session

NOW = 1_800_000_000.0
DAY = 86_400.0


def row(number: int, email: str, *, days_ago: float, cid: str = "", name: str = "", total: float = 89.0, fulfillment: str = "UNFULFILLED") -> dict:
    """A row as `OrderCache.rows()` holds it: flat, numeric, with the customer nested."""
    return {
        "order_id": f"gid://shopify/Order/{number}", "order_number": f"#{number}", "digits": str(number),
        "ts": NOW - days_ago * DAY, "created_at": "", "total": total, "currency": "GBP", "fulfillment": fulfillment,
        "customer": {"customer_id": cid or f"gid://shopify/Customer/{number}", "name": name or "Someone", "email": email},
    }


def thread(sender: str, subject: str, body: str = "", thread_id: str = "aa70d3f83dbef06e") -> dict:
    """A thread as gmail_read_thread returns it."""
    return {"thread_id": thread_id, "message_count": 1, "messages_shown": 1,
            "messages": [{"from": sender.split("@")[0], "from_email": sender, "subject": subject, "body": body, "date": "Thu, 10 Sep 2026 12:00:00 +0100"}]}


MIA = "mia.jones@example.com"
ROWS = [
    row(1938, MIA, days_ago=0, cid="gid://shopify/Customer/7001", name="Mia Jones"),
    row(1912, MIA, days_ago=45, cid="gid://shopify/Customer/7001", name="Mia Jones", total=65.0, fulfillment="FULFILLED"),
    row(1876, MIA, days_ago=120, cid="gid://shopify/Customer/7001", name="Mia Jones", total=74.0, fulfillment="FULFILLED"),
    row(1939, "david.randall@example.com", days_ago=0, cid="gid://shopify/Customer/7002", name="David Randall", total=65.0, fulfillment="FULFILLED"),
    row(1940, "priya.raman@example.com", days_ago=0, cid="gid://shopify/Customer/7004", name="Priya Raman", total=23.0),
]


def clock() -> float:
    return NOW


# ------------------------------------------------------------ thread → order (graph.py)


def test_a_number_in_the_subject_from_its_own_customer_is_a_confident_link():
    found = graph.linked_orders_for_thread(thread(MIA, "Order 1938 — can I add to it?", "Is it too late?"), rows=ROWS, clock=clock)
    assert found["confidence"] == "confident"
    assert [o["order_number"] for o in found["linked"]] == ["#1938"]
    assert found["linked"][0]["total"] == 89.0 and found["linked"][0]["fulfillment"] == "UNFULFILLED"
    assert found["provenance"] == ["order number 1938 in the subject", "sender is the customer on that order"]
    assert found["customer"] == {"customer_id": "gid://shopify/Customer/7001", "name": "Mia Jones"}


def test_a_number_in_the_body_counts_and_says_it_was_the_body():
    found = graph.linked_orders_for_thread(thread("priya.raman@example.com", "Cap", "Following up on my order 1940 — is it adjustable?"), rows=ROWS, clock=clock)
    assert found["confidence"] == "confident"
    assert [o["order_number"] for o in found["linked"]] == ["#1940"]
    assert found["provenance"][0] == "order number 1940 in the body"


def test_a_sender_with_exactly_one_recent_order_is_confident_without_a_number():
    found = graph.linked_orders_for_thread(thread("david.randall@example.com", "Hello", "Any news?"), rows=ROWS, clock=clock)
    assert found["confidence"] == "confident"
    assert [o["order_number"] for o in found["linked"]] == ["#1939"]
    assert found["provenance"] == ["sender is the customer on one recent order"]


def test_a_sender_with_several_recent_orders_is_possible_newest_first_and_capped():
    rows = ROWS + [row(1950, MIA, days_ago=3, cid="gid://shopify/Customer/7001", name="Mia Jones"), row(1949, MIA, days_ago=9, cid="gid://shopify/Customer/7001", name="Mia Jones")]
    found = graph.linked_orders_for_thread(thread(MIA, "Hello", "Which of my orders has shipped?"), rows=rows, clock=clock)
    assert found["confidence"] == "possible"
    # Four are within sixty days (1938, 1950, 1949, 1912); three are offered, newest first.
    assert [o["order_number"] for o in found["linked"]] == ["#1938", "#1950", "#1949"]
    assert found["provenance"] == ["sender is the customer on 4 recent orders"]
    assert found["customer"]["customer_id"] == "gid://shopify/Customer/7001", "the customer bridge holds whenever the sender is known"


def test_a_number_that_is_somebody_elses_order_is_possible_and_says_so():
    found = graph.linked_orders_for_thread(thread("stranger@example.net", "Order 1939", "I am collecting 1939 for David"), rows=ROWS, clock=clock)
    assert found["confidence"] == "possible"
    assert [o["order_number"] for o in found["linked"]] == ["#1939"]
    assert found["provenance"] == ["number 1939 in the subject, but the sender is not its customer"]
    assert found["customer"] is None, "a stranger bridges to nobody"


def test_a_number_of_somebody_elses_does_not_shake_a_customers_own_confident_link():
    found = graph.linked_orders_for_thread(thread("david.randall@example.com", "Re: 1940", "My friend's order 1940 arrived; where is mine?"), rows=ROWS, clock=clock)
    assert found["confidence"] == "confident"
    assert [o["order_number"] for o in found["linked"]] == ["#1939"]
    assert "number 1940 is mentioned but the sender is not its customer" in found["provenance"]


def test_nothing_matching_is_none_with_the_reason_and_never_a_name_match():
    # The From NAME is Mia's; the address is not. A name is not evidence.
    stranger = {"thread_id": "a413d264183cfe94", "messages": [{"from": "Mia Jones", "from_email": "mia.jones@elsewhere.example", "subject": "Hi", "body": "hello"}]}
    found = graph.linked_orders_for_thread(stranger, rows=ROWS, clock=clock)
    assert found == {"linked": [], "confidence": "none", "provenance": ["sender matches no recent order", "no order number in the thread"], "customer": None}


def test_a_customer_whose_orders_are_all_old_is_none_but_still_bridged():
    old = [row(1800, MIA, days_ago=200, cid="gid://shopify/Customer/7001", name="Mia Jones")]
    found = graph.linked_orders_for_thread(thread(MIA, "Hello again"), rows=old, clock=clock)
    assert found["confidence"] == "none" and found["linked"] == []
    assert found["provenance"][0].startswith("sender is a customer, but their orders are older than")
    assert found["customer"]["name"] == "Mia Jones"


def test_order_numbers_are_exact_four_or_five_digit_runs_not_parts_of_tracking_numbers():
    assert graph.order_numbers_in("tracking AB1234567890GB for #1938, ref 12345, year 2026, tel 07700900123") == ["1938", "12345", "2026"]
    assert graph.order_numbers_in("") == []


def test_a_listing_summary_is_read_the_same_way_as_a_full_thread():
    summary = {"thread_id": "aa70d3f83dbef06e", "from_email": MIA, "subject": "Order 1938 — can I add to it?", "snippet": "Is it too late?"}
    assert graph.linked_orders_for_thread(summary, rows=ROWS, clock=clock)["confidence"] == "confident"


# ------------------------------------------------------ the presenter's strip and the gate


class _WarmCache:
    clock = staticmethod(clock)

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def rows(self) -> list[dict]:
        return list(self._rows)

    def status(self) -> dict:
        return {"synced_at": NOW, "orders": len(self._rows)}


class _ColdCache(_WarmCache):
    def status(self) -> dict:
        return {"synced_at": None, "orders": 0}


@pytest.fixture()
def warm(monkeypatch):
    from app.tools import analytics_tools

    monkeypatch.setattr(analytics_tools, "_cache", _WarmCache(ROWS))


def _card(result: dict, session: Session | None = None) -> dict:
    (card,) = present([ToolCall(name="gmail_read_thread", args={"thread_id": result["thread_id"]}, ok=True, result=result)], session=session)
    return card["data"]


def test_the_thread_card_carries_the_linked_order_with_money_and_status(warm):
    data = _card(thread(MIA, "Order 1938 — can I add to it?"))
    assert data["link_confidence"] == "confident"
    assert data["linked_order"] == {
        "order_id": "gid://shopify/Order/1938", "order_number": "#1938", "total": "£89.00", "fulfillment": "unfulfilled",
        "customer_name": "Mia Jones", "customer_id": "gid://shopify/Customer/7001",
    }
    assert data["possible_orders"] == []
    assert data["linked_customer"] == {"customer_id": "gid://shopify/Customer/7001", "name": "Mia Jones"}
    assert data["link_provenance"] == ["order number 1938 in the subject", "sender is the customer on that order"]


def test_the_thread_card_offers_possible_orders_and_no_linked_one(warm):
    data = _card(thread(MIA, "Which has shipped?"))
    assert data["link_confidence"] == "possible" and data["linked_order"] is None
    assert [o["order_number"] for o in data["possible_orders"]] == ["#1938", "#1912"]


def test_the_linked_ids_are_issued_so_a_tap_on_the_strip_passes_the_gate(warm):
    from app.commands import Ctx, may_open

    session = Session(session_id="s")
    _card(thread(MIA, "Which has shipped?"), session)
    assert {"gid://shopify/Order/1938", "gid://shopify/Order/1912", "gid://shopify/Customer/7001"} <= session.issued_ids
    ctx = Ctx(runtime=None, session=session, branch=None)
    assert may_open(ctx, "order", "gid://shopify/Order/1938") and may_open(ctx, "customer", "gid://shopify/Customer/7001")
    assert not may_open(ctx, "order", "gid://shopify/Order/1939"), "an order the strip did not show stays refused"


def test_a_cold_cache_is_said_to_be_cold_not_reported_as_no_order(monkeypatch):
    from app.tools import analytics_tools

    monkeypatch.setattr(analytics_tools, "_cache", _ColdCache([]))
    data = _card(thread(MIA, "Order 1938 — can I add to it?"))
    assert data["link_confidence"] == "none" and data["linked_order"] is None and data["possible_orders"] == []
    assert data["link_provenance"] == ["order cache not warm"]
    # No cache bound at all (a Mac without Shopify) is the same honest answer.
    monkeypatch.setattr(analytics_tools, "_cache", None)
    assert _card(thread(MIA, "Order 1938"))["link_provenance"] == ["order cache not warm"]


# --------------------------------------------------------- order → threads (order.py)


def test_correlate_threads_runs_the_other_way_with_provenance():
    from app.context.order import correlate_threads

    found = correlate_threads([
        {"thread_id": "aa70d3f83dbef06e", "from_email": MIA, "subject": "Order 1938 — can I add to it?", "snippet": "", "authenticated": True},
        {"thread_id": "fe128e8f1ec5a51e", "from_email": MIA, "subject": "Order 1912 arrived", "snippet": "", "authenticated": False},
        {"thread_id": "c28cf65d31fe6cbb", "from_email": "priya.raman@example.com", "subject": "Cap", "snippet": "my order 1938?", "authenticated": True},
        {"thread_id": "a413d264183cfe94", "from_email": "no-reply@shipping.example", "subject": "Report", "snippet": "", "authenticated": True},
    ], customer_email=MIA, digits="1938")
    by_id = {t["thread_id"]: t for t in found}
    assert by_id["aa70d3f83dbef06e"]["match"] == "both" and by_id["aa70d3f83dbef06e"]["verified_sender"] is True
    assert by_id["fe128e8f1ec5a51e"]["match"] == "sender" and by_id["fe128e8f1ec5a51e"]["verified_sender"] is False
    assert by_id["c28cf65d31fe6cbb"]["match"] == "order_number" and by_id["c28cf65d31fe6cbb"]["provenance"] == "UNKNOWN"
    assert "a413d264183cfe94" not in by_id


async def test_the_hydrator_carries_the_threads_on_the_order_read_model():
    from app.context.order import Hydrator
    from experience.fixtures import FixtureShopify
    from experience.fixtures import data as world

    asked: list[dict] = []

    async def threads_for(**kwargs):
        asked.append(kwargs)
        return {"available": True, "threads": [
            {"thread_id": "aa70d3f83dbef06e", "from_email": world.MIA.email, "subject": "Order 1938 — can I add to it?", "snippet": "Is it too late?", "authenticated": True},
        ]}

    hydrator = Hydrator(lambda: FixtureShopify(), threads_for=threads_for)
    order = await hydrator.order("gid://shopify/Order/1938", budget_s=2.0)
    assert asked and asked[0]["sender"] == world.MIA.email and "#1938" in asked[0]["terms"], "the correlation asks by the customer's address and the order's number"
    threads = order["email"]["threads"]
    assert [t["thread_id"] for t in threads] == ["aa70d3f83dbef06e"]
    assert threads[0]["sender_match"] is True and threads[0]["match"] == "both"
    assert "email" not in order["pending"]


def test_graph_never_reads_a_source():
    """The presenter calls this; it must be a pure function over rows it was handed."""
    import inspect

    source = inspect.getsource(graph)
    for forbidden in ("graphql", "service()", "httpx", "gmail_tools", "shopify_tools", "await "):
        assert forbidden not in source, forbidden
    assert time.time  # the clock is injectable, and the default is the wall clock


# --------------------------------------------------- needs reply: across threads, without noise


def _inbox(threads_by_sender: dict[str, list[dict]], states: dict[str, dict], *, own: str = ""):
    """Bind a fake read side for `_customer_threads`: the listing per sender and the per-thread
    reply state, exactly the two things the production code asks for."""
    from app.tools import analytics_tools

    async def threads_for(**kwargs):
        return {"available": True, "threads": list(threads_by_sender.get(kwargs.get("sender", ""), []))}

    async def reply_state(thread_id: str):
        return states.get(thread_id)

    analytics_tools.bind_email(threads_for, None, reply_state, own_address=own or None)
    return analytics_tools


def _summary(thread_id: str, sender: str, subject: str, *, bulk: bool = False, authenticated: bool = True) -> dict:
    return {"thread_id": thread_id, "from_email": sender, "subject": subject, "snippet": "", "likely_bulk": bulk, "authenticated": authenticated}


def _state(thread_id: str, *, inbound: int | None, outbound: int | None) -> dict:
    return {"thread_id": thread_id, "latest_inbound_at": inbound, "latest_outbound_at": outbound}


@pytest.fixture()
def unbound():
    from app.tools import analytics_tools

    yield
    analytics_tools.bind_email(None, None)


async def test_a_reply_in_a_second_later_thread_answers_the_first(unbound):
    """Mia wrote in thread A on Monday; we answered in thread B on Tuesday. She is not waiting."""
    tools = _inbox(
        {MIA: [_summary("aa70d3f83dbef06e", MIA, "Order 1938 — can I add to it?"), _summary("bb70d3f83dbef06f", MIA, "Re: your cap")]},
        {"aa70d3f83dbef06e": _state("aa70d3f83dbef06e", inbound=1_000, outbound=None), "bb70d3f83dbef06f": _state("bb70d3f83dbef06f", inbound=None, outbound=2_000)},
    )
    out = await tools._customer_threads(MIA, ["1938"], 30, clock=clock)
    assert out["needs_reply"] is False and out["latest_direction"] == "outbound"
    assert out["provenance"]["threads_checked"] == 2 and out["provenance"]["thread_ids"] == ["aa70d3f83dbef06e", "bb70d3f83dbef06f"]
    assert out["provenance"]["related_orders"] == ["1938"] and out["confidence"] == "confident"


async def test_a_reply_older_than_the_latest_inbound_leaves_them_waiting(unbound):
    tools = _inbox(
        {MIA: [_summary("aa70d3f83dbef06e", MIA, "Order 1938"), _summary("bb70d3f83dbef06f", MIA, "Another thing")]},
        {"aa70d3f83dbef06e": _state("aa70d3f83dbef06e", inbound=3_000, outbound=None), "bb70d3f83dbef06f": _state("bb70d3f83dbef06f", inbound=1_000, outbound=2_000)},
    )
    out = await tools._customer_threads(MIA, ["1938"], 30, clock=clock)
    assert out["needs_reply"] is True and out["latest_direction"] == "inbound"
    assert out["provenance"]["latest_inbound_at"] == 3_000 and out["provenance"]["latest_outbound_at"] == 2_000


async def test_marketing_and_abandoned_cart_threads_never_count_as_the_customer_writing(unbound):
    """Only the automated threads mention the number; the customer never wrote. Not waiting,
    and — the part the September queue got wrong — not "emailed us" either."""
    tools = _inbox(
        {MIA: [
            _summary("c000000000000001", "no-reply@shop.example", "Abandoned checkout: order 1938", bulk=True),
            _summary("c000000000000002", "notifications@carrier.example", "Shipment 1938 update"),
            _summary("c000000000000003", "checkout@shop.example", "You left something in your cart"),
        ]},
        {"c000000000000001": _state("c000000000000001", inbound=5_000, outbound=None),
         "c000000000000002": _state("c000000000000002", inbound=5_000, outbound=None),
         "c000000000000003": _state("c000000000000003", inbound=5_000, outbound=None)},
    )
    out = await tools._customer_threads(MIA, ["1938"], 30, clock=clock)
    assert out["count"] == 0 and out["needs_reply"] is False and out["latest_direction"] == "none"
    assert out["confidence"] == "none" and out["provenance"]["threads_checked"] == 0
    assert out["provenance"]["ignored"] == 3 and out["provenance"]["ignored_why"] == ["automated", "bulk"]


async def test_our_own_address_is_outbound_not_a_customer_writing_in(unbound):
    """We emailed Mia first, naming her order; she has not answered. Nobody is waiting on US."""
    tools = _inbox(
        {MIA: [_summary("d000000000000001", "orders@crooksldn.example", "Your order 1938")]},
        {"d000000000000001": _state("d000000000000001", inbound=None, outbound=7_000)},
        own="orders@crooksldn.example",
    )
    out = await tools._customer_threads(MIA, ["1938"], 30, clock=clock)
    assert out["count"] == 0 and out["needs_reply"] is False
    assert out["provenance"]["ignored_why"] == ["ours"]


async def test_a_thread_from_another_address_that_names_their_order_is_possible_not_confident(unbound):
    tools = _inbox(
        {MIA: [_summary("e000000000000001", "mia.at.work@corp.example", "About 1938", authenticated=True)]},
        {"e000000000000001": _state("e000000000000001", inbound=1_000, outbound=None)},
    )
    out = await tools._customer_threads(MIA, ["1938"], 30, clock=clock)
    assert out["needs_reply"] is True, "still offered — a customer writing from a second address is real"
    assert out["confidence"] == "possible" and out["related_orders"] == ["1938"]
    # Her own address, unauthenticated and naming no order, is possible too: a From header is a claim.
    tools = _inbox({MIA: [_summary("e000000000000002", MIA, "Hello", authenticated=False)]},
                   {"e000000000000002": _state("e000000000000002", inbound=1_000, outbound=None)})
    assert (await tools._customer_threads(MIA, ["1938"], 30, clock=lambda: NOW + 1))["confidence"] == "possible"


async def test_email_query_rows_carry_the_provenance(unbound, monkeypatch):
    """The row the queue is built from says how it was decided, not only what it decided."""
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from app.analytics import sets as working_sets
    from app.analytics.cache import CacheView
    from app.tools import analytics_tools
    from app.tools.dispatch import dispatch

    tools = _inbox({MIA: [_summary("aa70d3f83dbef06e", MIA, "Order 1938 — can I add to it?")]},
                   {"aa70d3f83dbef06e": _state("aa70d3f83dbef06e", inbound=1_000, outbound=None)})

    class _Cache:
        clock = staticmethod(clock)

        async def view(self, period, *, timeout_s=0.0):
            return CacheView(rows=[{"order_id": "gid://shopify/Order/1938", "order_number": "#1938", "ts": NOW, "customer": {"customer_id": "gid://shopify/Customer/7001", "name": "Mia Jones", "email": MIA}}],
                             complete=True, covered_days=90, synced_at=NOW, syncing=False)

        def _client(self):
            class _C:
                async def timezone(self):
                    return ZoneInfo("Europe/London")
            return _C()

    async def _now():
        return datetime.fromtimestamp(NOW, tz=UTC), UTC

    monkeypatch.setattr(analytics_tools, "_cache", _Cache())
    monkeypatch.setattr(analytics_tools, "_now_and_zone", _now)

    session = Session(session_id="s-prov")
    ws = working_sets.create(session, kind="customers", members=["gid://shopify/Customer/7001"], label="Recent customers")
    calls: list = []
    await dispatch("email_query", {"set_id": ws.set_id, "days": 30}, session=session, timeout_s=5, calls=calls)
    (row,) = calls[-1].result["rows"]
    assert row["needs_reply"] is True and row["related_orders"] == ["1938"] and row["confidence"] == "confident"
    assert row["provenance"]["thread_ids"] == ["aa70d3f83dbef06e"] and row["provenance"]["latest_direction"] == "inbound"
    assert tools is analytics_tools


# ------------------------------------------------------------- the queue, and asking again


def _needs_reply(session: Session, rows: list[dict]):
    from app.fastpath.library import _needs_reply_render
    from app.fastpath.models import Ctx
    from app.reads.scheduler import ReadResult
    from app.session.branch import Branch

    ctx = Ctx(runtime=None, session=session, branch=Branch(branch_id="b", session_id=session.session_id), intent=None, text="who needs replying to")
    # The inbox read (`email_query` with no set), which is what the recipe asks for now.
    result = ReadResult(values={"mail": {"scope": "inbox", "days": 30, "window_complete": True, "threads_listed": 12, "threads_checked": 12,
                                         "rows": rows, "counts": {"people": len(rows), "unchecked": 0}}})
    return _needs_reply_render(ctx, result)


MIA_ROW = {"customer_id": "gid://shopify/Customer/7001", "customer_name": "Mia Jones", "customer_email": MIA, "orders": ["#1938", "#1912"],
           "emailed": True, "threads": 1, "replied": False, "last_subject": "Order 1938 — can I add to it?", "last_thread_id": "aa70d3f83dbef06e",
           "checked": True, "thread_count": 1, "latest_inbound_at": 1_000, "latest_outbound_at": None, "latest_direction": "inbound",
           "has_reply_after_latest_inbound": False, "needs_reply": True, "related_orders": ["1938"], "confidence": "confident"}
PRIYA_ROW = {**MIA_ROW, "customer_id": "gid://shopify/Customer/7004", "customer_name": "Priya Raman", "last_thread_id": "c28cf65d31fe6cbb",
             "orders": ["#1940"], "related_orders": [], "confidence": "possible"}


def test_the_scope_is_said_once_and_the_repeat_is_short():
    from app.fastpath import library

    session = Session(session_id="s-again")
    first = _needs_reply(session, [MIA_ROW])
    assert first.answer == "1 person is waiting on a reply in the inbox's last 30 days: Mia Jones."
    assert session.last_needs_reply_at > 0
    again = _needs_reply(session, [MIA_ROW])
    assert again.answer == "Still just Mia."
    assert again.surfaces, "the queue is still drawn; only the sentence is shorter"
    several = _needs_reply(session, [MIA_ROW, PRIYA_ROW])
    assert several.answer == "Still Mia and Priya."
    # Past the window it is a fresh question again, scope and all.
    session.last_needs_reply_at -= library.NEEDS_REPLY_REPEAT_S + 1
    assert _needs_reply(session, [MIA_ROW]).answer.startswith("1 person is waiting on a reply in the inbox's last 30 days")
    # And nobody, asked again, is "still nobody" rather than the count read twice.
    session.last_needs_reply_at -= library.NEEDS_REPLY_REPEAT_S + 1
    assert _needs_reply(session, []).answer == "Nobody is waiting on a reply in the inbox's last 30 days — 12 threads from people checked."
    assert _needs_reply(session, []).answer == "Still nobody."


def test_the_queue_rows_carry_the_related_orders_and_the_confidence():
    from app.fastpath.library import _waiting_surface

    surface = _waiting_surface([MIA_ROW, PRIYA_ROW])
    mia, priya = surface.data["threads"]
    assert mia["related_orders"] == ["1938"] and mia["confidence"] == "confident"
    assert priya["related_orders"] == [] and priya["confidence"] == "possible"
    # The confidence is CARRIED, which is what this test is named for and what has not
    # changed: both rows still hold it, and the renderer and any later consumer can read it.
    #
    # What changed is the SNIPPET, which is the line on the glass. It read "#1938 ·
    # confident" and "#1940 · possible" — `confident` and `possible` are how
    # app/families/order_email.py grades a link, and the Phase 5 visual pass photographed one
    # of them on the tablet. Neither is a thing a person says, which puts them in the same
    # class as EMPTY and THESE: a machine word that reached the surface (§26).
    #
    # The old expectation was wrong on both rows, and differently on each. A CERTAIN link
    # needs no adjective — the order number is the claim, and "confident" adds a word that
    # only invites the question of what the uncertain case looks like. An UNCERTAIN one must
    # be visibly uncertain, because the row is a decision to reply and a wrong link is a
    # reply to the wrong question; "possible" as a trailing token is the weakest possible way
    # to say that, sitting where a reader has already taken the number as fact.
    assert mia["snippet"] == "#1938", "the thread's own order, and no adjective on a certain link"
    assert priya["snippet"] == "maybe #1940", (
        "no number in the thread: the recent orders stand in, and the doubt is said FIRST, "
        "before the number a reader would otherwise take as fact")


# ------------------------------------------------- order → email → draft (app/families/order_email.py)


def order(number: int = 1938, *, email: str = MIA, name: str = "Mia Jones", oid: int | None = None) -> dict:
    """An order as `shopify_order_detail` returns it (app/context/order.py:shape_order), with
    only the keys this family reads."""
    return {
        "order_id": f"gid://shopify/Order/{oid or number}", "order_number": f"#{number}",
        "customer_name": name, "customer_email": email, "total": "£89.00",
        "fulfillment": "UNFULFILLED", "placed_at": "2026-09-10T08:00:00Z",
    }


def message(sender: str, *, body: str, date: str, subject: str = "Order 1938 — can I add to it?") -> dict:
    return {"from": sender.split("@")[0].replace(".", " ").title(), "from_email": sender,
            "subject": subject, "body": body, "date": date}


THEIRS = "Thu, 10 Sep 2026 12:00:00 +0100"
OURS = "Thu, 10 Sep 2026 14:30:00 +0100"


def test_a_thread_naming_this_order_from_its_own_customer_is_this_orders_thread():
    from app.families import order_email

    confidence, why = order_email.about_this_order(
        {"thread_id": "aa70d3f83dbef06e", "from_email": MIA, "subject": "Order 1938 — can I add to it?", "snippet": "Is it too late?"},
        order=order(1938), rows=ROWS, clock=clock)
    assert confidence == "confident"
    assert why == ["order number 1938 in the subject", "sender is the customer on that order"]


def test_a_thread_about_another_of_their_orders_is_not_this_orders_thread():
    """The mistake this family exists to avoid: David HAS written, about #1939, and the order
    on screen is #1929. A reply written into that thread answers the wrong parcel."""
    from app.families import order_email

    confidence, why = order_email.about_this_order(
        {"thread_id": "58361c4d87dfeee5", "from_email": "david.randall@example.com", "subject": "Where is 1939?", "snippet": "Any tracking yet?"},
        order=order(1929, email="david.randall@example.com", name="David Randall"), rows=ROWS, clock=clock)
    assert confidence == "none"
    assert why == ["the thread is about #1939, not this order"]


def test_a_name_is_never_evidence_that_a_thread_is_about_an_order():
    from app.families import order_email

    impostor = {"thread_id": "a413d264183cfe94", "from_email": "mia.jones@elsewhere.example", "subject": "Hello", "snippet": "any news?"}
    confidence, _ = order_email.about_this_order(impostor, order=order(1938), rows=ROWS, clock=clock)
    assert confidence == "none"


def test_a_cold_cache_falls_back_to_the_narrow_rule_and_never_upgrades_a_guess():
    """With no rows the Mac cannot tell this order from the customer's others, so the address
    alone is POSSIBLE — and possible is never replied from."""
    from app.families import order_email

    named = {"thread_id": "aa70d3f83dbef06e", "from_email": MIA, "subject": "Order 1938 — can I add to it?", "snippet": ""}
    bare = {"thread_id": "aa70d3f83dbef06e", "from_email": MIA, "subject": "Delivery address", "snippet": "the house number"}
    stranger = {"thread_id": "aa70d3f83dbef06e", "from_email": "someone@else.example", "subject": "About 1938", "snippet": ""}
    assert order_email.about_this_order(named, order=order(1938), rows=[], clock=clock)[0] == "confident"
    assert order_email.about_this_order(bare, order=order(1938), rows=[], clock=clock)[0] == "possible"
    assert order_email.about_this_order(stranger, order=order(1938), rows=[], clock=clock)[0] == "possible"
    chosen, confidence, _ = order_email._choose([bare], order=order(1938), rows=[], clock=clock)
    assert chosen is None and confidence == "possible", "a possible link is shown, not replied to"


def test_the_newest_confident_thread_is_the_one_a_reply_would_go_into():
    from app.families import order_email

    old = {"thread_id": "old", "from_email": MIA, "subject": "Order 1938", "snippet": "", "date": "Mon, 07 Sep 2026 09:00:00 +0100"}
    new = {"thread_id": "new", "from_email": MIA, "subject": "Order 1938 again", "snippet": "", "date": THEIRS}
    chosen, confidence, _ = order_email._choose([old, new], order=order(1938), rows=ROWS, clock=clock)
    assert confidence == "confident" and chosen["thread_id"] == "new"


def test_the_reply_state_is_read_from_the_thread_and_says_who_is_waiting():
    from app.families import order_email

    waiting = order_email.reply_state([message(MIA, body="Is it too late to add a cap?", date=THEIRS)],
                                      customer_email=MIA, now=NOW)
    assert waiting["latest_direction"] == "inbound" and waiting["replied"] is False
    assert waiting["last_from"] == "Mia" and waiting["latest_outbound_at"] is None

    answered = order_email.reply_state(
        [message(MIA, body="Any tracking?", date=THEIRS),
         message("orders@crooksldn.example", body="It went out today.", date=OURS)],
        customer_email=MIA, now=NOW)
    assert answered["latest_direction"] == "outbound" and answered["replied"] is True
    assert answered["last_from"] == "us"
    # A reply we sent BEFORE their latest message has not answered it.
    reopened = order_email.reply_state(
        [message("orders@crooksldn.example", body="It went out today.", date=THEIRS),
         message(MIA, body="It has not arrived.", date=OURS)],
        customer_email=MIA, now=NOW)
    assert reopened["latest_direction"] == "inbound" and reopened["replied"] is False


def test_every_stamp_gmail_hands_over_is_understood_and_an_unreadable_one_is_not_guessed():
    from app.families import order_email

    assert order_email._stamp("Thu, 10 Sep 2026 12:00:00 +0100") == pytest.approx(1_789_038_000.0)
    assert order_email._stamp("1789038000000") == pytest.approx(1_789_038_000.0)
    assert order_email._stamp("2026-09-10T11:00:00Z") == pytest.approx(1_789_038_000.0)
    assert order_email._stamp("sometime last week") is None
    assert order_email._stamp("") is None
    # A message with no readable date is left out of the fold rather than counted as now: it
    # would otherwise become the "latest" and turn a five-hour wait into "just now".
    state = order_email.reply_state(
        [message(MIA, body="first", date=THEIRS), message(MIA, body="second", date="who knows")],
        customer_email=MIA, now=NOW)
    assert state["messages"] == 2 and state["latest_inbound_at"] == pytest.approx(1_789_038_000.0)


def test_the_continuation_names_the_draft_tool_with_both_ids_and_quotes_each_side():
    from app.families import order_email

    thread = {"thread_id": "aa70d3f83dbef06e", "subject": "Order 1938 — can I add to it?", "message_count": 2,
              "messages": [message(MIA, body="Is it too late to add a cap?", date=THEIRS),
                           message("orders@crooksldn.example", body="Let me check the packing table.", date=OURS)]}
    state = order_email.reply_state(thread["messages"], customer_email=MIA, now=NOW)
    prompt = order_email.continuation_prompt(order=order(1938), thread=thread, state=state)
    assert "gmail_draft_reply(thread_id='aa70d3f83dbef06e', order_id='gid://shopify/Order/1938', body=…)" in prompt
    assert "In one sentence say what they actually want done" in prompt
    # And the mechanical half is claimed by the Mac, not asked of the model: `_render`'s
    # sentence leads the answer, so a prompt that asked for it again would have the owner
    # hear who wrote and whether we replied twice in one breath.
    assert "Do not repeat that." in prompt
    assert "issued to you" in prompt and "never send it yourself" in prompt
    assert "Is it too late to add a cap?" in prompt, "the model must not have to read the thread again"
    assert "Latest from us" in prompt and "Let me check the packing table." in prompt


def test_the_continuation_is_bounded_and_the_instruction_is_never_what_gets_cut():
    from app.families import order_email

    huge = {"thread_id": "aa70d3f83dbef06e", "subject": "Order 1938 " * 40, "message_count": 40,
            "messages": [message(MIA, body="what I want is " + "x" * 40_000, date=THEIRS),
                         message("orders@crooksldn.example", body="y" * 40_000, date=OURS)]}
    state = order_email.reply_state(huge["messages"], customer_email=MIA, now=NOW)
    prompt = order_email.continuation_prompt(order=order(1938), thread=huge, state=state)
    assert len(prompt) <= order_email.CONTINUATION_CHARS, len(prompt)
    assert "gmail_draft_reply(thread_id='aa70d3f83dbef06e'" in prompt
    assert "what I want is" in prompt, "the beginning of what they said survives the trim"
    # And a budget too small for any quote still produces the ask and the instruction.
    tiny = order_email.continuation_prompt(order=order(1938), thread=huge, state=state, limit=600)
    assert "gmail_draft_reply" in tiny and "Do not read it again" in tiny


def test_the_compound_sentence_is_this_familys_and_a_bare_draft_stays_claudes():
    """The two routing facts this family turns on, asserted rather than assumed.

    "Check whether they've emailed us … and draft the reply" opens with a question word, so
    `mutating()` is False and the fast lane may serve it. "Draft the reply" on its own is a
    mutation and `resolve` refuses it — which is right: `gmail_draft_reply` writes, and this
    lane cannot.
    """
    from app.families import load_all
    from app.fastpath import recipe_for, resolve

    load_all()

    class _Branch:
        entity = {"kind": "order", "ref": "gid://shopify/Order/1938", "label": "#1938"}
        set_id = ""
        workflow = None
        resolutions: dict = {}

    compound = resolve("Check whether they've emailed us about this, tell me what they're waiting for, and draft the reply", branch=_Branch())
    assert compound.family == "order_email_draft", compound.public()
    recipe = recipe_for(compound.family)
    assert recipe is not None and recipe.recipe_id == "order_email_reply"
    assert compound.confidence >= recipe.min_confidence, "it would not reach the fast lane"

    assert resolve("what are they waiting for", branch=_Branch()).family == "order_email_waiting"
    assert resolve("have they emailed about this order", branch=_Branch()).family == "order_email_draft"
    assert resolve("check whether they've emailed us about this and draft the reply", branch=_Branch()).family == "order_email_draft"

    for asked in ("draft the reply", "and draft the reply", "reply to her about this"):
        refused = resolve(asked, branch=_Branch())
        assert refused.family == "" and refused.reason == "asks for a change", asked

    # Nothing else this branch might be asked is taken away from the family that answers it.
    assert resolve("where is it", branch=_Branch()).family == "order_status_lookup"
    assert resolve("what else has this customer ordered", branch=_Branch()).family == "customer_history_lookup"
    assert resolve("what's in the inbox", branch=_Branch()).family == "inbox_state"
    assert resolve("which customers need replying to", branch=_Branch()).family == "needs_reply"

    # With nothing open there is no order to be about, so the turn is Claude's.
    class _Empty(_Branch):
        entity = None

    assert resolve("have they emailed about this order", branch=_Empty()).family == ""


def test_an_unpadded_gmail_body_still_has_words_in_it():
    """Gmail's `body.data` is base64url and its padding is not guaranteed. Unpadded, it raised
    inside `_decode_part`, the raise was swallowed, and the message HAD NO BODY — so the reply
    state and the continuation prompt had nothing but a subject line to work from. The fixture
    inbox encodes exactly that way (experience/fixtures/data.py)."""
    import base64

    from app.tools.gmail_tools import _decode_part

    text = "Hi, I have just placed order 1938. Is it too late to add a cap to it? Thanks, Mia."
    unpadded = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
    assert len(unpadded) % 4 != 0, "this fixture no longer exercises the unpadded case"
    assert _decode_part({"mimeType": "text/plain", "body": {"data": unpadded}}) == text
    assert _decode_part({"mimeType": "text/plain", "body": {"data": ""}}) == ""
    assert _decode_part({"mimeType": "text/plain", "body": {"data": "!!!not base64!!!"}}) == ""


def test_a_sentence_that_names_a_number_is_not_answered_from_the_order_on_screen():
    """"Any email from him about 1938" is two candidate subjects — the record on screen and a
    number that may be an order, a tracking number or a year, because a bare one is
    deliberately never extracted as an order number. The recipe declines to plan it and Claude
    takes the turn, which is how it was answered in September."""
    from app.families import load_all
    from app.fastpath.intent import resolve
    from app.fastpath.models import Ctx
    from app.fastpath.recipes import RECIPES
    from app.reads.scheduler import ReadResult
    from app.session.branch import Branch
    from app.session.models import Session

    load_all()
    recipe = RECIPES["order_email_reply"]
    session = Session(session_id="s-number")
    branch = Branch(branch_id="b", session_id="s-number")
    branch.visit("order", MIA_ORDER_ID := "gid://shopify/Order/1938", "#1938")

    def ctx_for(text: str) -> Ctx:
        return Ctx(runtime=None, session=session, branch=branch, intent=resolve(text, branch=branch), text=text)

    about_this = ctx_for("have they emailed about this order")
    assert recipe.plan(about_this) is not None, "the deictic question is exactly what this recipe is for"
    assert [r.name for r in recipe.plan(about_this).reads] == ["detail", "threads", "thread"]
    assert recipe.plan(about_this).reads[0].args == {"order_id": MIA_ORDER_ID}

    for named in ("any email from him about 1938", "has she emailed about 1936"):
        declined = ctx_for(named)
        assert recipe.plan(declined) is None, named
        assert recipe.render(declined, ReadResult()).defer, named

    # And with nothing open there is nothing for "this" to mean.
    empty = Ctx(runtime=None, session=session, branch=Branch(branch_id="b2", session_id="s-number"),
                intent=resolve("have they emailed about this order", branch=None), text="have they emailed about this order")
    assert recipe.plan(empty) is None
