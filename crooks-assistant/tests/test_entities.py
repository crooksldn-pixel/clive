"""One id, one entity — the canonical presentation graph (§6).

The live session drew the same customer twice in one interface. His words, turn_541df4c7a2b6:
"You just pulled up two in the same UI". The cause was structural: every tool result became
its own card, so a customer touched by `shopify_find_customer`, `shopify_customer_history` and
`gmail_search` became three surfaces about one person.

These tests hold the fix, which is upstream of any renderer: reads are folded into entities
keyed by CANONICAL IDENTITY before presentation is asked anything. One customer id is one
customer. A later read PATCHES the entity it belongs to; it never adds a second one and it
never erases what the first one established.

Provenance stays available inside the graph — which tool supplied which field — because that
is what makes a wrong value traceable. It is presentation that deduplicates, not the record.
"""

from __future__ import annotations

from app import entities
from app.session.models import Session

CUSTOMER = "gid://shopify/Customer/7"
ORDER_A = "gid://shopify/Order/1962"
ORDER_B = "gid://shopify/Order/1930"

FIND_CUSTOMER = {
    "query": "daniel",
    "customers": [{"customer_id": CUSTOMER, "name": "Daniel Stub", "email": "daniel@example.com",
                   "orders": 2, "spent": "120.00 GBP"}],
}
HISTORY = {
    "customer_id": CUSTOMER, "name": "Daniel Stub", "orders": 2, "spent": "120.00 GBP",
    "standing": "returning", "since": "2026-03-01",
    "last_order": {"order_id": ORDER_A, "order_number": "CROOKS-1962"},
    "recent": [
        {"order_id": ORDER_A, "order_number": "CROOKS-1962", "total": "60.00 GBP",
         "placed_at": "2026-09-01T10:00:00Z", "fulfillment": "FULFILLED", "payment": "PAID"},
        {"order_id": ORDER_B, "order_number": "CROOKS-1930", "total": "60.00 GBP",
         "placed_at": "2026-08-02T10:00:00Z", "fulfillment": "FULFILLED", "payment": "PAID"},
    ],
}
GMAIL = {
    "query": "daniel@example.com",
    "threads": [{"thread_id": "t-1", "from": "Daniel Stub", "from_email": "daniel@example.com",
                 "subject": "Where is my order", "date": "Mon", "snippet": "Any news?"}],
}


def graph() -> entities.EntityGraph:
    """A fresh graph. The graph is deliberately per CONVERSATION and outlives a turn — that
    is what D-3 turns on — so a test that wants an empty one says so."""
    entities.forget("entities")
    return entities.graph_for(Session(session_id="entities"))


# --------------------------------------------------------------------------- identity


def test_a_gid_and_a_bare_id_are_the_same_entity():
    """Shopify hands back `gid://shopify/Customer/7`; a cache row, a working set and a tap
    hand back `7`. They are one customer, and a graph that thinks otherwise draws two."""
    assert entities.key("customer", CUSTOMER) == entities.key("customer", "7")
    assert entities.key("order", ORDER_A) == entities.key("order", "1962")
    assert entities.key("order", ORDER_A) == entities.key("order", "#1962")
    # And a kind is part of the identity: customer 7 is not order 7.
    assert entities.key("customer", "7") != entities.key("order", "7")


def test_an_id_of_the_wrong_kind_is_not_folded_into_an_entity():
    """A gid names its own kind. A customer gid handed in as an order is a bug in a caller,
    not a new order, and the graph must not invent one."""
    g = graph()
    assert g.patch("order", CUSTOMER, {"order_number": "CROOKS-1"}) is None
    assert g.of_kind("order") == []


# ------------------------------------------------------------------ patching, not adding


def test_three_reads_of_one_customer_leave_one_entity_with_all_three_findings():
    """§6, exactly: shopify_find_customer → shell; shopify_customer_history → enrich .orders;
    gmail_search → enrich .email. NOT three cards, and not three records either."""
    g = graph()
    g.ingest("shopify_find_customer", FIND_CUSTOMER)
    g.ingest("shopify_customer_history", HISTORY)
    g.ingest("gmail_search", GMAIL)

    people = g.of_kind("customer")
    assert len(people) == 1, [p.ident for p in people]
    person = people[0]
    assert person.fields["name"] == "Daniel Stub"
    assert person.fields["orders"] == 2
    assert person.fields["spent"] == "120.00 GBP"
    # The history read enriched the SAME entity's orders. The graph holds what the shop said
    # — "CROOKS-1962" — because it is a record of reads and provenance has to mean something;
    # "#1962" is a presentation decision and is made in app/workspace.py, once, where §26 is
    # enforced for every surface rather than in each read's own fold.
    assert [o.fields["order_number"] for o in g.orders_of(person.key)] == ["CROOKS-1962", "CROOKS-1930"]
    assert [o.ident for o in g.orders_of(person.key)] == ["1962", "1930"]
    # ...and the Gmail read enriched the same entity's email, by the address the shop gave.
    assert [t.fields["subject"] for t in g.threads_of(person.key)] == ["Where is my order"]


def test_ten_reads_touching_one_customer_leave_one_entity():
    """The regression from the live session's seven-card turn, at the graph level: one entity
    touched by ten reads is one entity."""
    g = graph()
    for _ in range(5):
        g.ingest("shopify_find_customer", FIND_CUSTOMER)
        g.ingest("shopify_customer_history", HISTORY)
    assert len(g.of_kind("customer")) == 1
    assert len(g.of_kind("order")) == 2, "two order ids are two orders; five reads of them are not ten"


def test_an_order_id_is_one_order_and_a_thread_id_is_one_email():
    g = graph()
    g.ingest("shopify_find_order", {"orders": [{"order_id": ORDER_A, "order_number": "CROOKS-1962",
                                                "total": "60.00 GBP", "customer_id": CUSTOMER,
                                                "customer_name": "Daniel Stub"}]})
    g.ingest("shopify_order_detail", {"order_id": ORDER_A, "order_number": "CROOKS-1962",
                                      "total": "60.00 GBP", "payment": "PAID", "fulfillment": "FULFILLED",
                                      "customer_id": CUSTOMER, "customer_name": "Daniel Stub",
                                      "items": [{"title": "Yard Jeans", "variant": "M", "quantity": 1,
                                                 "total": "60.00 GBP"}]})
    g.ingest("gmail_read_thread", {"thread_id": "t-1", "messages": [
        {"message_id": "m1", "from": "Daniel Stub", "from_email": "daniel@example.com",
         "subject": "Where is my order", "body": "Any news?", "date": "Mon"}]})
    g.ingest("gmail_search", GMAIL)

    assert len(g.of_kind("order")) == 1
    assert len(g.of_kind("email_thread")) == 1
    # The detail read enriched the order the find read established, rather than replacing it.
    order = g.of_kind("order")[0]
    assert order.fields["payment"] == "PAID" and order.fields["items"]
    # A find read establishes the customer of an order, so the order has somewhere to belong.
    assert g.get("customer", CUSTOMER) is not None


def test_an_empty_result_does_not_erase_what_is_held():
    """§27 at the graph level. A Gmail search that matched nothing is a fact about the inbox,
    never a reason to forget who the customer is."""
    g = graph()
    g.ingest("shopify_customer_history", HISTORY)
    g.ingest("gmail_search", {"query": "daniel@example.com", "threads": []})
    person = g.get("customer", CUSTOMER)
    assert person is not None and person.fields["orders"] == 2
    assert g.orders_of(person.key), "the held orders survived an empty inbox read"
    assert g.threads_of(person.key) == []


def test_a_thinner_later_read_never_blanks_a_field_already_known():
    """`shopify_find_order` on a list returns a summary; the detail read returns everything.
    They arrive in either order, and the card must not lose the items because a summary of
    the same order landed second."""
    g = graph()
    g.ingest("shopify_order_detail", {"order_id": ORDER_A, "order_number": "CROOKS-1962",
                                      "payment": "PAID", "total": "60.00 GBP",
                                      "items": [{"title": "Yard Jeans", "quantity": 1}]})
    g.ingest("shopify_find_order", {"orders": [{"order_id": ORDER_A, "order_number": "CROOKS-1962",
                                                "payment": "", "total": ""}]})
    order = g.of_kind("order")[0]
    assert order.fields["payment"] == "PAID"
    assert order.fields["total"] == "60.00 GBP"
    assert order.fields["items"]


# --------------------------------------------------------------------------- provenance


def test_provenance_says_which_read_supplied_which_field():
    """Presentation deduplicates identity; the record keeps the trail. A wrong number on a
    card has to be traceable to the tool that produced it."""
    g = graph()
    g.ingest("shopify_find_customer", FIND_CUSTOMER)
    g.ingest("shopify_customer_history", HISTORY)
    person = g.get("customer", CUSTOMER)
    assert person.provenance["name"] == "shopify_find_customer"
    assert person.provenance["standing"] == "shopify_customer_history"
    assert person.sources == ("shopify_find_customer", "shopify_customer_history")


def test_the_graph_is_per_conversation_and_is_the_same_graph_each_time():
    """Held facts are what D-3 is about: the second turn must find the first turn's customer.
    Two conversations must not find each other's."""
    mine, yours = Session(session_id="mine"), Session(session_id="yours")
    entities.graph_for(mine).ingest("shopify_customer_history", HISTORY)
    assert entities.graph_for(mine).get("customer", CUSTOMER) is not None
    assert entities.graph_for(yours).get("customer", CUSTOMER) is None


def test_the_graph_is_bounded():
    """A conversation cannot grow an unbounded graph, and neither can the process."""
    g = graph()
    for n in range(entities.MAX_ENTITIES * 2):
        g.patch("order", f"gid://shopify/Order/{n}", {"order_number": f"CROOKS-{n}"})
    assert len(g) <= entities.MAX_ENTITIES
    # The most recently touched survive; the oldest are dropped.
    assert g.get("order", f"gid://shopify/Order/{entities.MAX_ENTITIES * 2 - 1}") is not None
