"""One customer's history in one place, newest first (app/customers/history.py).

George, 2 October 2026: "Clive should understand the history of this customer, through emails
where they are related, to orders and the whole broader Clive ecosystem."

The customer read already made two reads — their orders from Shopify and their inbox from Gmail.
Those two now carry what became of each order (shipped, refunded and whether the money went
back, a staff note) and every thread to them, from them and about their orders; and CLIVE's own
records are folded in beside them: the work list, the screens' packed marks, the changes CLIVE
made, and — for the owner only — his objectives that name them. Every assertion here is about
what the owner sees on the card and what the model is told, and that the story costs no more
reads than the customer card already made.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from app.customers import history
from tests.customers_world import ALICIA, cards, result, say, world_fixture

world = pytest.fixture(world_fixture)


async def _story(world, **kwargs) -> tuple[dict, dict]:
    body = await say(world, "show me Alicia Grant's history", ("shopify_find_customer", {"query": "Alicia Grant"}),
                     ("shopify_customer_history", {"customer_id": ALICIA}), **kwargs)
    return body, result(world, "shopify_customer_history")


def _whats(timeline: dict) -> list[str]:
    return [r["what"] for r in timeline["rows"]]


async def test_orders_shipping_refunds_notes_and_email_both_ways_newest_first(world):
    body, told = await _story(world)
    timeline = told["timeline"]
    assert _whats(timeline) == [
        "Refunded £45.00 on #2201",
        "Royal Mail wrote about #2201: Delivery update for CROOKS-2201",
        "We emailed them: Re: Gift receipt for my hoodie order",
        "Emailed us: Gift receipt for my hoodie order",
        "Shipped #2201",
        "Ordered #2201",
        "Note on #2201",
        "Shipped #2150",
        "Ordered #2150",
    ]
    rows = {r["what"]: r for r in timeline["rows"]}
    assert rows["Refunded £45.00 on #2201"]["detail"].startswith("Refund of £45.00 to Visa ending 4242 succeeded on ")
    assert rows["Note on #2201"]["detail"] == "Asked for a gift receipt"
    assert rows["Emailed us: Gift receipt for my hoodie order"]["ref_kind"] == "email_thread"
    assert rows["Ordered #2201"]["ref"] == "gid://shopify/Order/2201"
    # A thread that is about nobody of theirs is not in their story.
    assert not any("Wholesale" in w for w in _whats(timeline))
    assert timeline["sources"]["Shopify"] == "2 orders" and timeline["sources"]["Gmail"] == "3 threads"
    # The card: the same rows, in a History tab, bounded and copied key by key.
    customer = [c for c in cards(body, "customer") if c.get("timeline")][-1]
    assert [r["what"] for r in customer["timeline"]["rows"]] == _whats(timeline)
    assert {"name": "Gmail", "said": "3 threads"} in customer["timeline"]["sources"]


async def test_the_story_costs_no_shopify_read_the_customer_card_did_not_already_make(world):
    await _story(world)
    shopify = [q.split("(")[0].split()[-1] for q, _ in world.store.queries if "Scopes" not in q]
    assert shopify == ["FindCustomers", "CrooksCustomerOrders"]
    # Two inbox reads: the one the customer card always made — from them, exactly as before —
    # and the wide one the story is made from, which never stands in for the first.
    sender_only, wide = sorted(world.inbox.calls, key=lambda c: len(c["terms"]))
    assert sender_only == {"sender": "alicia.grant@example.com", "terms": [], "days": 60, "limit": 3}
    assert wide["sender"] == "alicia.grant@example.com"
    assert wide["terms"] == ["alicia.grant@example.com", "CROOKS-2201", "#2201", "CROOKS-2150", "#2150"]
    assert wide["days"] == 365


async def test_the_threads_from_them_are_still_what_the_email_tab_shows(world):
    _body, told = await _story(world)
    assert [t["thread_id"] for t in told["email_threads"]["threads"]] == ["19a0c0ffee000001"]


async def test_her_own_email_stays_when_couriers_have_written_more_since(world):
    """Ten newer couriers' threads naming her order fill the wide search; her own email is read
    by the search that only looks for her, so it is still on her card and still the model's."""
    from datetime import time as clock
    from datetime import timedelta

    from tests.customers_world import LONDON, TODAY

    stamp = datetime.combine(TODAY - timedelta(days=1), clock(9, 0), LONDON).strftime("%a, %d %b %Y %H:%M:%S %z")
    couriers = [{"thread_id": f"19a0c0ffee0001{n:02d}", "message_id": f"c{n}", "from": "Royal Mail",
                 "from_email": "noreply@royalmail.example", "subject": f"Tracking update {n} for CROOKS-2201",
                 "date": stamp, "snippet": "Your parcel is on its way", "likely_bulk": False, "authenticated": True}
                for n in range(10)]
    world.inbox.held[:0] = couriers
    body, told = await _story(world)
    assert [t["thread_id"] for t in told["email_threads"]["threads"]] == ["19a0c0ffee000001"]
    card = [c for c in cards(body, "customer") if c.get("timeline")][-1]
    assert "Gift receipt for my hoodie order" in str(card)


async def test_what_clive_recorded_about_them_is_in_their_story(world, monkeypatch, tmp_path):
    from app.actions import engine
    from app.displays import store as displays
    from app.objectives import store as objectives
    from app.objectives.store import ObjectiveStore
    from app.work.store import work

    # The work list: their order claimed and packed.
    monkeypatch.setattr(work, "_folder", tmp_path / "work")
    job = work.claim_found(ref="order:gid://shopify/Order/2201", kind="pack_order", title="Pack #2201", details="", who="owner")
    work.packed(job.item_id, who="owner", owner=True)
    # A screen's Mark packed on their other order.

    class Screens:
        def done(self, *, order=None, limit=10, ref=None):
            return [{"kind": "order", "title": "Order #2150", "ref": "gid://shopify/Order/2150", "screen": "Studio TV",
                     "how": "screen", "done_at": "2026-08-24T07:30:00Z"}] if order == "2150" else []

    monkeypatch.setattr(displays, "_STORE", Screens())
    # A refund CLIVE made, proven, in the action ledger (ids and outcomes, never content).
    engine._engine.ledger._append({"ts": time.time() - 60, "event": "VERIFIED", "operation": "refund_create",
                                   "entity_ref": "gid://shopify/Order/2201", "status": "VERIFIED"})
    engine._engine.ledger._append({"ts": time.time() - 30, "event": "PROPOSED", "operation": "order_cancel",
                                   "entity_ref": "gid://shopify/Order/2201"})
    # One of the owner's objectives that names her.
    held = ObjectiveStore(tmp_path / "objectives")
    held.create(title="Make it right with Alicia Grant", request="Alicia Grant's hoodie needs a gift receipt", by="owner")
    held.create(title="Drop 4 samples", request="samples for the next drop", by="owner")
    monkeypatch.setattr(objectives, "_STORE", held)

    _body, told = await _story(world)
    whats = _whats(told["timeline"])
    assert "Packed #2201" in whats and "Claimed #2201" in whats
    assert "Packed #2150" in whats
    assert "CLIVE refunded #2201" in whats, "a proven change of CLIVE's is history"
    assert not any("cancelled" in w for w in whats if w.startswith("CLIVE")), "a change that never ran is not"
    assert "Objective: Make it right with Alicia Grant" in whats and "Objective: Drop 4 samples" not in whats
    rows = {r["what"]: r for r in told["timeline"]["rows"]}
    assert rows["Packed #2201"]["detail"] == "work list · you"
    assert rows["Packed #2150"]["detail"] == "packed on the Studio TV: marked with that screen's own button"
    assert rows["CLIVE refunded #2201"]["detail"] == "proven"
    sources = told["timeline"]["sources"]
    assert sources["work list"] == "2 steps" and sources["CLIVE's changes"] == "1 change" and sources["objectives"] == "1 objective"


def test_the_owners_objectives_are_his_own():
    """A member of the team asking about a customer is told everything but the owner's own records."""
    rows, said = history._objective_rows("Alicia Grant", "alicia.grant@example.com", {}, owner=False)
    assert rows == [] and said == "the owner's own"


def test_the_owners_screens_are_his_own_too(monkeypatch):
    """A member of the team is not shown what the owner's screens marked."""
    from app.displays import store as displays

    class Screens:
        def done(self, *, order=None, limit=10, ref=None):
            return [{"kind": "order", "title": "Order #2150", "ref": "gid://shopify/Order/2150", "screen": "Studio TV",
                     "how": "screen", "done_at": "2026-08-24T07:30:00Z"}]

    monkeypatch.setattr(displays, "_STORE", Screens())
    story = {"recent": [{"order_id": "gid://shopify/Order/2150", "order_number": "CROOKS-2150", "placed_at": "2026-08-20T10:00:00Z"}],
             "orders": 1, "email": "a@example.com"}
    staff = history.timeline(story, [], owner=False, today=datetime.now(UTC).date())
    assert "Packed #2150" not in _whats(staff) and staff["sources"]["screens"] == "the owner's own"
    owner = history.timeline(story, [], owner=True, today=datetime.now(UTC).date())
    assert "Packed #2150" in _whats(owner)


def test_an_order_number_counts_only_as_an_order_is_written_and_unrelated_threads_are_left_out():
    """"#2201" or "CROOKS-2201" names her order; a bare 2201 (an invoice, a street) does not, and a
    thread that is neither from her, from us, nor about her order is not hers to show."""
    threads = [
        {"thread_id": "a1", "from": "Royal Mail", "from_email": "noreply@royalmail.example", "subject": "Parcel CROOKS-2201",
         "snippet": "", "date": "Tue, 29 Sep 2026 08:00:00 +0100"},
        {"thread_id": "a2", "from": "Printer", "from_email": "jobs@printer.example", "subject": "Your order #2201 is late",
         "snippet": "", "date": "Tue, 29 Sep 2026 09:00:00 +0100"},
        {"thread_id": "a3", "from": "Accounts", "from_email": "accounts@supplier.example", "subject": "Invoice 2201",
         "snippet": "Payment due", "date": "Tue, 29 Sep 2026 10:00:00 +0100"},
        {"thread_id": "a4", "from": "Someone", "from_email": "someone@example.net", "subject": "Hello",
         "snippet": "Hi", "date": "Tue, 29 Sep 2026 11:00:00 +0100"},
    ]
    story = {"recent": [{"order_id": "gid://shopify/Order/2201", "order_number": "CROOKS-2201", "placed_at": "2026-09-20T10:00:00Z"}],
             "orders": 1, "email": "alicia.grant@example.com"}
    told = history.timeline(story, threads, owner=True, ours="studio@crooks.example", today=datetime.now(UTC).date())
    mail = [r["ref"] for r in told["rows"] if r["source"] == "Gmail"]
    assert sorted(mail) == ["a1", "a2"]


def test_an_inbox_that_was_not_read_says_so_rather_than_looking_empty():
    told = history.timeline({"recent": [], "orders": 0, "email": "a@example.com"}, None, owner=True,
                            today=datetime.now(UTC).date())
    assert told["sources"]["Gmail"] == "not read" and told["rows"] == []


async def test_the_customer_workspace_activity_is_the_same_story(world):
    """The composed customer page's Activity section is this story, not its own thinner one."""
    from app import entities, workspace

    await _story(world)
    person = entities.graph_for(world.runtime.sessions.get("c1")).newest("customer")
    assert person is not None and person.get("timeline")
    rows = workspace._activity_rows([], [], person.get("timeline"))
    assert rows[0] == {"what": "Refunded £45.00 on #2201", "when": rows[0]["when"],
                       "detail": rows[0]["detail"]} and rows[0]["detail"].startswith("Refund of £45.00 to Visa")
