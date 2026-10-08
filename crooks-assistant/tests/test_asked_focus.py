"""What he asked for always shows; what CLIVE adds unasked is about the same customer, order or thread.

George, 8 October 2026 (DEC-071 ruling 25, built as DEC-073): "asking to see todays orders and to show
a specific order s different to asking to see a specific order and seeing the specific order +
todays orders. in one instance it was asked, in the other, the ai inferred it was needed when it
wasnt specified. clive can infer but inferring needs stronger relation, for instance, asking about a
customers email can give detailed explanation as to why with other cards, not just showing the
reason. this can be its tracking status, an instagram message. they were't asked for but if theyre
relevant they are inferred, asking to see the customers email and it showing you every other email
from other people today is not what we want to happen."

The model says what he asked to see (`asked_for`, app/tools/asked_for.py); `app/focus.py` chooses the
cards from that and from what the cards themselves say they are about, never from his words (MAP
rule 7). The golden world's David Replica stands in for the customer: he asked "Where is 1939?", and
#1939 is fulfilled with a Royal Mail tracking number. Scripted through the real gate, presenters and
turn (`experience/harness.py`): what is held is what the Mac does with those calls, not that Claude
would make them.
"""

from __future__ import annotations

import time

import pytest

from app import focus, progressive
from app.providers.base import ToolCall
from experience.fixtures import data
from experience.harness import harness, order_reads

DAVIDS_THREAD = "58361c4d87dfeee5"      # "Where is 1939?" — his question, and our answer with the tracking
MIAS_THREAD = "aa70d3f83dbef06e"        # "Order 1938 — can I add to it?" — somebody else's email today
PRIYAS_THREAD = "c28cf65d31fe6cbb"      # "Cap" — her question about order 1940
O1939, O1940, O1938 = (data.BY_NAME[n].order_id for n in ("#1939", "#1940", "#1938"))


@pytest.fixture()
async def world():
    progressive.reset()
    async with harness(admitted=True) as h:
        yield h
    progressive.reset()


def _cards(said) -> list[dict]:
    return [item for item in said.ui if item.get("type") != "context_stack"]


def _kinds(said) -> list[str]:
    return [c["type"] for c in _cards(said)]


def _numbers(said) -> list[str]:
    return [str(c["data"].get("order_number") or "") for c in _cards(said) if c["type"] == "order"]


def _asked(*, records=(), lists=()) -> tuple[str, dict]:
    return ("asked_for", {"records": list(records), "lists": list(lists)})


# ---------------------------------------------------------------- the two-part ask


async def test_today_s_orders_and_open_1940_shows_the_list_and_the_order(world):
    """What he asked for always shows: both parts of the ask, the list and the record."""
    said = await world.ask("show me today's orders and open 1940", ("shopify_list_orders", {"days": 1}),
                           ("shopify_order_detail", {"order_id": O1940}), _asked(records=["1940"], lists=["shopify_list_orders"]),
                           session_id="two-part", reply="Three today; 1940 is open.")
    assert not said.unmakeable, said.unmakeable
    kinds = _kinds(said)
    assert kinds[0] == "order_list" and "order" in kinds, kinds
    assert _cards(said)[0]["data"]["orders"], "today's orders are on it"
    assert _numbers(said) == ["#1940"], kinds


async def test_today_s_orders_and_1940_and_not_the_search_for_another_customer_s_orders(world):
    """The review's note 2: a list is named by the read that drew it, so naming today's orders
    does not bring in a search the model ran for somebody else's orders on the way."""
    said = await world.ask("show me today's orders and open 1940", ("shopify_list_orders", {"days": 1}),
                           ("shopify_find_order", {"query": "Mia Jones"}), ("shopify_order_detail", {"order_id": O1940}),
                           _asked(records=["1940"], lists=["shopify_list_orders"]),
                           session_id="two-part-search", reply="Three today; 1940 is open.")
    assert all(c.get("ok") for c in said.raw["tool_calls"]), said.raw["tool_calls"]
    # One list on the screen, today's: it has David's and Priya's orders on it, which the search
    # for Mia's could not.
    lists = [c["data"] for c in _cards(said) if c["type"] in ("order_list", "order_match")]
    assert len(lists) == 1, _kinds(said)
    assert {"#1939", "#1940"} <= {o.get("order_number") for o in lists[0].get("orders") or []}, lists
    assert _numbers(said) == ["#1940"], _kinds(said)


async def test_today_s_emails_and_the_reply_and_not_the_search_that_found_her_thread(world):
    """"Today's emails, and reply to Priya": today's inbox, named by its read, and the reply. The
    "cap" search that found her thread is how the model got there, and stays off."""
    said = await world.ask("show me today's emails and reply to priya", ("gmail_search", {"query": "cap"}),
                           ("gmail_search", {"query": "newer_than:1d"}),
                           ("gmail_send_reply", {"thread_id": PRIYAS_THREAD, "body": "Hi Priya, yes: the black cap is the adjustable one."}),
                           _asked(records=[PRIYAS_THREAD], lists=["gmail_search newer_than:1d"]),
                           session_id="inbox-and-reply", reply="Today's email, and the reply to Priya.")
    assert all(c.get("ok") for c in said.raw["tool_calls"]), said.raw["tool_calls"]
    kinds = _kinds(said)
    assert kinds[0] == "confirmation" and _cards(said)[0]["data"]["entity_ref"] == PRIYAS_THREAD, kinds
    searched = [c["data"]["query"].split() for c in _cards(said) if c["type"] == "email_list"]
    assert len(searched) == 1 and "cap" not in searched[0] and "newer_than:1d" in searched[0], searched


async def test_a_list_named_by_words_its_one_read_does_not_share_is_not_that_read(world):
    """The re-review's note R1: only the "cap" search ran, and the model named today's inbox by
    words that search was never given. The search is how her thread was found, not what he asked
    to see: the reply alone, as DEC-069 shows it."""
    said = await world.ask("show me the email reply to priya", ("gmail_search", {"query": "cap"}),
                           ("gmail_send_reply", {"thread_id": PRIYAS_THREAD, "body": "Hi Priya, yes: the black cap is the adjustable one."}),
                           _asked(records=[PRIYAS_THREAD], lists=["gmail_search newer_than:1d"]),
                           session_id="one-search-misnamed", reply="Here's the reply to Priya.")
    assert all(c.get("ok") for c in said.raw["tool_calls"]), said.raw["tool_calls"]
    assert _kinds(said) == ["confirmation"], _kinds(said)


async def test_asked_for_one_order_today_s_orders_read_on_the_way_stay_off(world):
    """The other half of his sentence: asked for one order, today's orders the model read to find it
    are not what he asked for and are not about that order as a whole: they stay off."""
    said = await world.ask("show me 1940", ("shopify_list_orders", {"days": 1}),
                           ("shopify_order_detail", {"order_id": O1940}), _asked(records=["#1940"]),
                           session_id="one-order", reply="1940.")
    assert "order_list" not in _kinds(said) and _numbers(said) == ["#1940"], _kinds(said)


async def test_the_same_reads_without_the_model_saying_are_today_s_rules(world):
    """The model said nothing about what he asked for: DEC-069's rules decide, as before — a
    record read in full wins over the list."""
    said = await world.ask("show me today's orders and open 1940", ("shopify_list_orders", {"days": 1}),
                           ("shopify_order_detail", {"order_id": O1940}), session_id="unsaid", reply="1940.")
    assert "order_list" not in _kinds(said) and _numbers(said) == ["#1940"], _kinds(said)


# ---------------------------------------------- the customer's email, and what is about it


def _instagram(who: str, text: str) -> str:
    """A conversation on Instagram, kept as the webhook would keep it: invented, in the golden world."""
    from app.messaging import instagram as channel
    from app.messaging.models import Message
    from app.messaging.store import store

    thread = channel.dm_thread(f"ig-fixture-{who}", "ig-account-fixture")
    thread.who = who
    store.upsert(thread)
    store.add(thread, Message(message_id=f"m_{time.time_ns()}", chat_id=thread.chat_id, direction="in", origin="contact",
                              text=text, at=time.time() - 600, language="en", english=text,
                              translation_state="not_needed", remote_id=f"igmid.fixture{time.time_ns()}"))
    return thread.chat_id


def _chat_of(handle: str):
    def chat(calls) -> dict:
        threads = next(c.result["threads"] for c in reversed(calls) if c.name == "messages_recent")
        return {"chat_id": next(t["chat_id"] for t in threads if t["from"] == handle)}
    return chat


async def test_the_customer_s_email_with_their_tracking_and_instagram_message_and_not_other_people_s(world):
    """His example, read for read: today's inbox searched (everyone's email today), today's orders,
    David's email opened — what he asked for — his order read (its tracking is on it), and the
    Instagram conversations read, his among someone else's, then his opened. His email, his order
    with its tracking and his Instagram message are the screen; nobody else's email, the inbox,
    today's orders and the inbox of messages are not."""
    davids = _instagram("@david.replica", "Did my parcel go out? Order 1939")
    _instagram("@someone.else", "Do you ship to Spain?")
    said = await world.ask(
        "show me david's email",
        ("gmail_search", {"query": "newer_than:1d"}),
        ("shopify_list_orders", {"days": 1}),
        ("gmail_read_thread", {"thread_id": DAVIDS_THREAD}),
        ("gmail_read_thread", {"thread_id": MIAS_THREAD}),
        ("shopify_order_detail", {"order_id": O1939}),
        ("messages_recent", {}),
        ("message_thread", _chat_of("@david.replica")),
        _asked(records=[DAVIDS_THREAD]),
        session_id="davids-email", reply="He asked where 1939 is; it went Royal Mail.")
    assert all(c.get("ok") for c in said.raw["tool_calls"]), said.raw["tool_calls"]
    cards = _cards(said)
    kinds = [c["type"] for c in cards]
    assert kinds[0] == "email_thread" and cards[0]["data"]["thread_id"] == DAVIDS_THREAD, kinds
    # His order, with its tracking on it.
    assert _numbers(said) == ["#1939"], kinds
    (order,) = [c["data"] for c in cards if c["type"] == "order"]
    assert order["fulfillments"] and order["fulfillments"][0]["number"] == "AB1234567890GB", order["fulfillments"]
    # His Instagram message, and only his conversation.
    (messages,) = [c["data"] for c in cards if c["type"] == "messages"]
    assert messages["view"] == "thread" and messages["thread"]["chat_id"] == davids, messages
    # Nobody else's: not Mia's email, not the inbox, not today's orders, not everyone's messages.
    threads = [c["data"]["thread_id"] for c in cards if c["type"] == "email_thread"]
    assert threads == [DAVIDS_THREAD], threads
    assert not {"email_list", "order_list"} & set(kinds), kinds
    flat = repr(said.ui)
    assert data.MIA.email not in flat and "@someone.else" not in flat


# ---------------------------------------------------------------- the reply to a customer


def _the_reply_turn() -> tuple[tuple[str, dict], ...]:
    """DEC-069's turn, read for read, and two records read in full on the way: her order (about
    her) and Mia's email (about somebody else)."""
    return (
        ("shopify_find_customer", {"query": "Priya Raman"}),
        ("gmail_search", {"query": "cap"}),
        ("gmail_search", {"query": "newer_than:1d"}),
        ("shopify_list_orders", {"days": 1}),
        ("gmail_read_thread", {"thread_id": MIAS_THREAD}),
        ("shopify_order_detail", {"order_id": O1940}),
        ("gmail_send_reply", {"thread_id": PRIYAS_THREAD, "body": "Hi Priya, yes: the black cap is the adjustable one."}),
    )


async def test_the_reply_is_still_the_reply_on_top_with_nothing_unrelated(world):
    """The reply to her, named as what he asked for: the reply card first, then only what is
    about her — her order — and none of the searches, nobody else's email, nor today's orders."""
    said = await world.ask("show me the email reply to priya", *_the_reply_turn(), _asked(records=[PRIYAS_THREAD]),
                           session_id="reply-asked", reply="Here's the reply to Priya.")
    kinds = _kinds(said)
    assert kinds[0] == "confirmation", kinds
    assert _cards(said)[0]["data"]["entity_ref"] == PRIYAS_THREAD
    assert _numbers(said) == ["#1940"], kinds
    assert set(kinds) <= {"confirmation", "order", "attention"}, kinds
    flat = repr(said.ui)
    assert MIAS_THREAD not in flat and data.MIA.email not in flat


async def test_the_reply_with_nothing_said_is_still_the_reply_alone(world):
    """Without the model saying what he asked for, DEC-069's rule 1: the reply card alone."""
    said = await world.ask("show me the email reply to priya", *_the_reply_turn(), session_id="reply-unsaid",
                           reply="Here's the reply to Priya.")
    assert _kinds(said) == ["confirmation"], _kinds(said)


async def test_beside_the_reply_her_customer_record_he_did_not_name_stays_off(world):
    """The review's note 1, and his 7 October line: "it showed [a customer]'s total orders as a
    customer ... when all I wanted to see was the reply". Her whole history read on the way, the
    reply prepared, the thread named as what he asked for: the reply card alone. Priya Raman is
    the golden world's invented customer (experience/fixtures/data.py)."""
    said = await world.ask(
        "show me the email reply to priya",
        ("shopify_find_customer", {"query": "Priya Raman"}),
        ("shopify_customer_history", {"customer_id": data.PRIYA.customer_id}),
        ("gmail_search", {"query": "cap"}),
        ("gmail_search", {"query": "newer_than:1d"}),
        ("gmail_send_reply", {"thread_id": PRIYAS_THREAD, "body": "Hi Priya, yes: the black cap is the adjustable one."}),
        _asked(records=[PRIYAS_THREAD]),
        session_id="reply-history", reply="Here's the reply to Priya.")
    assert all(c.get("ok") for c in said.raw["tool_calls"]), said.raw["tool_calls"]
    assert _kinds(said) == ["confirmation"], _kinds(said)
    assert _cards(said)[0]["data"]["entity_ref"] == PRIYAS_THREAD


# ---------------------------------------------------------------- two orders, and a list walked


async def test_two_orders_asked_for_side_by_side_are_both_on_the_screen(world):
    """"Put 1938 and 1940 side by side", named: both orders, whichever is drawn as its line."""
    said = await world.ask("put 1938 and 1940 side by side", *order_reads("1938"), *order_reads("1940"),
                           _asked(records=["1938", "1940"]), session_id="side-asked", reply="Both are up.")
    assert sorted(_numbers(said)) == ["#1938", "#1940"], _kinds(said)


async def test_a_list_he_asked_for_out_loud_is_still_walked_with_next(world):
    """The spoken list walk (`app/routes/turn.py` `_walk_what_was_listed`) is decided from the
    answer's cards: today's orders, named as asked, are still one list he can walk."""
    said = await world.ask("show me today's orders", ("shopify_list_orders", {"days": 1}), _asked(lists=["shopify_list_orders"]),
                           session_id="walk-asked", reply="Today's orders.")
    assert _kinds(said) == ["order_list"], _kinds(said)
    workflow = said.raw["branch"]["workflow"]
    assert workflow and workflow["total"] == len(_cards(said)[0]["data"]["orders"]), workflow
    moved = await world.touch("workflow.next", session_id="walk-asked")
    assert moved.raw["ok"] is True and moved.raw["answer"].endswith(f"1 of {workflow['total']}."), moved.raw


# ---------------------------------------------------------------- over the cards alone


ORDER_1939 = {"type": "order", "data": {"order_id": O1939, "order_number": "#1939", "detail": True,
                                         "customer_id": data.DAVID.customer_id, "customer_email": data.DAVID.email,
                                         "customer_name": "David Replica"}}
LINES_1939 = {"type": "attention", "data": {"for": O1939, "items": [{"title": "Tracking not scanned"}]}}
HIS_EMAIL = {"type": "email_thread", "data": {"thread_id": DAVIDS_THREAD, "messages": [
    {"from": "David Replica", "from_email": data.DAVID.email, "body": "Where is 1939?", "outbound": False},
    {"from": "CROOKS", "from_email": "orders@crooksldn.example", "body": "Royal Mail.", "outbound": True}]}}
TRACKING = {"type": "shipping", "data": {"view": "one", "order_number": "#1939", "tracking": True,
                                          "shipments": [{"shipment_id": "shp_fixture1", "order_number": "#1939"}]}}
HIS_DM = {"type": "messages", "data": {"view": "thread", "thread": {"chat_id": "chat_fixture_david", "who": "@david.replica"}}}
HER_EMAIL = {"type": "email_thread", "data": {"thread_id": MIAS_THREAD, "messages": [
    {"from": "Mia Jones", "from_email": data.MIA.email, "body": "Can I add a cap?", "outbound": False}],
    "linked_order": {"order_id": O1938, "order_number": "#1938"}}}
INBOX = {"type": "email_list", "data": {"threads": [{"thread_id": MIAS_THREAD, "from_email": data.MIA.email},
                                                   {"thread_id": DAVIDS_THREAD, "from_email": data.DAVID.email}]}}
TODAY = {"type": "order_list", "data": {"orders": [{"order_id": O1938}, {"order_id": O1939}]}}
FOUND = {"type": "customer", "data": {"customer_id": data.DAVID.customer_id, "name": "David Replica"}}
NUMBERS = {"type": "metric_group", "data": {"metrics": [{"label": "Orders", "value": "4"}]}}
# The read that drew today's orders, named as the list he asked for.
LISTED = ToolCall(name="shopify_list_orders", args={"days": 1}, ok=True, result={})
TODAY_S_ORDERS = frozenset({("shopify_list_orders", frozenset())})


def test_an_unasked_card_shows_only_when_it_is_a_record_about_the_same_customer_order_or_thread():
    said = focus.Asked(records=frozenset({DAVIDS_THREAD}), lists=frozenset())
    why: dict = {}
    kept = focus.answer_cards([INBOX, TODAY, FOUND, HIS_EMAIL, HER_EMAIL, ORDER_1939, LINES_1939, TRACKING, HIS_DM, NUMBERS],
                              why, said=said)
    assert kept == [HIS_EMAIL, ORDER_1939, LINES_1939, TRACKING, HIS_DM], [c["type"] for c in kept]
    assert why == {"rule": "asked", "set_aside": ["email_list", "order_list", "customer", "email_thread", "metric_group"],
                   "added": ["order", "attention", "shipping", "messages"]}


HIS_HISTORY = {"type": "customer", "data": {"customer_id": data.DAVID.customer_id, "name": "David Replica",
                                            "email": data.DAVID.email, "history": {"orders": 2, "spent": "104.00"}}}


def test_a_customer_he_did_not_name_is_added_only_when_no_change_is_on_screen():
    """With nothing waiting for his hold, his customer read in full is about the same person as his
    email and is added (ruling 25). Beside a change it is not: the change is the screen, and a
    customer record there is the 7 October "total orders as a customer" card. Named, it shows."""
    said = focus.Asked(records=frozenset({DAVIDS_THREAD}), lists=frozenset())
    assert focus.answer_cards([HIS_EMAIL, HIS_HISTORY], said=said) == [HIS_EMAIL, HIS_HISTORY]
    reply = {"type": "confirmation", "data": {"proposal_id": "p1", "entity_ref": DAVIDS_THREAD,
                                              "message": {"channel": "email", "kind": "reply", "to": data.DAVID.email}}}
    workspace = {"type": "customer_workspace", "data": {"ref": data.DAVID.customer_id, "title": "David Replica",
                                                        "email": data.DAVID.email}}
    assert focus.answer_cards([HIS_HISTORY, workspace, reply], said=said, read_whole=frozenset({data.DAVID.customer_id})) == [reply]
    named = focus.Asked(records=frozenset({DAVIDS_THREAD, focus._norm(data.DAVID.customer_id)}), lists=frozenset())
    assert focus.answer_cards([HIS_HISTORY, reply], said=named) == [reply, HIS_HISTORY]


ANA = "ana.fixture@example.com"           # an invented second person on his thread
ANAS_THREAD = {"type": "email_thread", "data": {"thread_id": "thread_fixture_ana", "messages": [
    {"from": "Ana Fixture", "from_email": ANA, "body": "Separate question about returns.", "outbound": False}]}}
ANAS_DM = {"type": "messages", "data": {"view": "thread", "thread": {"chat_id": "chat_fixture_ana", "who": "@ana.fixture"}}}


def test_a_second_person_on_his_thread_does_not_bring_in_their_other_emails():
    """The review's note 3: a thread is about its linked customer, or else its first inbound sender,
    not everyone who wrote on it. Somebody else replying on his thread (a partner, staff forwarding
    it) does not make their own email today part of what he asked about."""
    said = focus.Asked(records=frozenset({DAVIDS_THREAD}), lists=frozenset())
    his = {"type": "email_thread", "data": {"thread_id": DAVIDS_THREAD, "messages": [
        {"from": "David Replica", "from_email": data.DAVID.email, "body": "Where is 1939?", "outbound": False},
        {"from": "Ana Fixture", "from_email": ANA, "body": "Following up for David.", "outbound": False}]}}
    assert focus.answer_cards([his, ANAS_THREAD, ANAS_DM, ORDER_1939], said=said) == [his, ORDER_1939]
    # Linked to a customer, the thread is about that customer, whoever wrote first.
    forwarded = {"type": "email_thread", "data": {"thread_id": DAVIDS_THREAD, "messages": [
        {"from": "Ana Fixture", "from_email": ANA, "body": "Forwarding David's question.", "outbound": False}],
        "linked_customer": {"customer_id": data.DAVID.customer_id, "name": "David Replica"}}}
    assert focus.answer_cards([forwarded, ANAS_THREAD, ORDER_1939, HIS_DM], said=said) == [forwarded, ORDER_1939, HIS_DM]


def test_a_card_added_for_the_subject_extends_it_by_ids_and_order_numbers_only():
    """An order linked to his email is added, and its id and number follow on (its tracking); its
    customer's email address and name do not, so another person's email and conversation stay off."""
    said = focus.Asked(records=frozenset({DAVIDS_THREAD}), lists=frozenset())
    his = {"type": "email_thread", "data": {"thread_id": DAVIDS_THREAD, "messages": [
        {"from": "David Replica", "from_email": data.DAVID.email, "body": "Where is 1977?", "outbound": False}],
        "linked_order": {"order_id": "gid://shopify/Order/fixture1977", "order_number": "#1977"}}}
    gift = {"type": "order", "data": {"order_id": "gid://shopify/Order/fixture1977", "order_number": "#1977", "detail": True,
                                      "customer_email": ANA, "customer_name": "Ana Fixture"}}
    tracking = {"type": "shipping", "data": {"view": "one", "order_number": "#1977",
                                             "shipments": [{"shipment_id": "shp_fixture1977", "order_number": "#1977"}]}}
    assert focus.answer_cards([his, gift, ANAS_THREAD, ANAS_DM, tracking], said=said) == [his, gift, tracking]


def test_a_first_name_alone_is_not_the_same_person():
    """A conversation carries no email or customer id: only a full name (or a handle that spells
    one) ties it to a customer. "David" could be anyone."""
    said = focus.Asked(records=frozenset({DAVIDS_THREAD}), lists=frozenset())
    first = {"type": "messages", "data": {"view": "thread", "thread": {"chat_id": "chat_a", "who": "David"}}}
    nobody = {"type": "messages", "data": {"view": "thread", "thread": {"chat_id": "chat_b", "who": "someone on Instagram"}}}
    full = {"type": "messages", "data": {"view": "thread", "thread": {"chat_id": "chat_c", "who": "David Replica"}}}
    assert focus.answer_cards([HIS_EMAIL, first, nobody, full], said=said) == [HIS_EMAIL, full]


def test_a_full_name_is_two_words_of_two_letters_once_titles_are_dropped():
    """The review's note 4: "Sam K", "J. Smith", "Mr Khan" and "Customer Service" are not anybody's
    full name, so a conversation called that is not tied to an email from someone called that."""
    for label in ("Sam K", "J. Smith", "Mr Khan", "Customer Service", "Dr Raman", "@sam_k", "Sam"):
        assert focus._name(label) == "", label
    assert focus._name("Dr Priya Raman") == "priya raman"
    assert focus._name("Mrs Ana Fixture <ana.fixture@example.com>") == "ana fixture"
    assert focus._name("Sam J Kelly") == "sam kelly"
    assert focus._name("@david.replica") == "david replica"
    for sender, other in (("Sam K", "Sam K"), ("Mr Khan", "Mr Khan"), ("Customer Service", "Customer Service")):
        said = focus.Asked(records=frozenset({"thread_fixture_label"}), lists=frozenset())
        email = {"type": "email_thread", "data": {"thread_id": "thread_fixture_label", "messages": [
            {"from": sender, "from_email": "sam.kelly@example.com", "body": "Hello", "outbound": False}]}}
        chat = {"type": "messages", "data": {"view": "thread", "thread": {"chat_id": "chat_fixture_label", "who": other}}}
        assert focus.answer_cards([email, chat], said=said) == [email], sender


def test_one_person_s_messages_are_about_them_and_everyone_s_are_not():
    said = focus.Asked(records=frozenset({DAVIDS_THREAD}), lists=frozenset())
    his = {"type": "messages", "data": {"view": "recent", "threads": [{"chat_id": "chat_a", "who": "@david.replica"}]}}
    everyone = {"type": "messages", "data": {"view": "recent", "threads": [{"chat_id": "chat_a", "who": "@david.replica"},
                                                                          {"chat_id": "chat_b", "who": "@someone.else"}]}}
    assert focus.answer_cards([HIS_EMAIL, everyone], said=said) == [HIS_EMAIL]
    assert focus.answer_cards([HIS_EMAIL, his], said=said) == [HIS_EMAIL, his]


def test_a_change_stays_on_top_and_an_error_is_never_set_aside():
    said = focus.Asked(records=frozenset(), lists=TODAY_S_ORDERS)
    change = {"type": "confirmation", "data": {"proposal_id": "p1", "entity_ref": O1940}}
    error = {"type": "error", "data": {"service": "gmail"}}
    kept = focus.answer_cards([TODAY, HER_EMAIL, change, error], said=said, drawn=[(TODAY, LISTED)])
    assert kept == [change, TODAY, error], [c["type"] for c in kept]


def test_what_the_model_names_that_nothing_drew_leaves_today_s_rules_to_decide():
    said = focus.Asked(records=frozenset({"9999"}), lists=frozenset({("returns_open", frozenset())}))
    cards = [INBOX, HIS_EMAIL, ORDER_1939, NUMBERS]
    why: dict = {}
    assert focus.answer_cards(cards, why, said=said) == focus.answer_cards(cards)
    assert why["rule"] == "record" and "added" not in why


def test_a_list_he_asked_for_is_not_the_subject_of_everything_on_its_rows():
    """Asked for today's orders only: an order the model opened on the way is not added for being
    one of its rows — that is the inferred card he does not want."""
    said = focus.Asked(records=frozenset(), lists=TODAY_S_ORDERS)
    assert focus.answer_cards([TODAY, ORDER_1939, LINES_1939, HIS_EMAIL], said=said, drawn=[(TODAY, LISTED)]) == [TODAY]


def test_a_list_is_named_by_its_read_and_the_words_pick_out_which_one():
    """Two searches of the same tool: the words named pick out the read; a tool named bare, when
    both of its reads had words, picks out neither; a tool that ran once is that read. A "nearly
    fits" find is no list of orders."""
    inbox = {"type": "email_list", "data": {"threads": [{"thread_id": MIAS_THREAD}]}}
    caps = {"type": "email_list", "data": {"threads": [{"thread_id": PRIYAS_THREAD}]}}
    drawn = [(inbox, ToolCall(name="gmail_search", args={"query": "newer_than:1d", "days": 1}, ok=True, result={})),
             (caps, ToolCall(name="gmail_search", args={"query": "cap"}, ok=True, result={}))]

    def shown(*lists: str) -> list[dict]:
        said = focus.asked_by_the_model([ToolCall(name="asked_for", args={}, ok=True, result={"records": [], "lists": list(lists)})])
        return focus.answer_cards([inbox, caps], said=said, drawn=drawn)

    assert shown("gmail_search newer_than:1d") == [inbox]
    assert shown("gmail_search cap") == [caps]
    assert shown("gmail_search newer_than:1d", "gmail_search cap") == [inbox, caps]
    assert shown("gmail_search") == focus.answer_cards([inbox, caps]), "named bare, neither is picked out"
    assert focus.answer_cards([inbox], said=focus.Asked(frozenset(), frozenset({("gmail_search", frozenset())})),
                              drawn=drawn[:1]) == [inbox]
    assert focus.list_kind({"type": "order_match", "data": {"rows": []}}) == ""


def test_what_the_model_said_is_read_from_its_calls_and_not_from_his_words():
    said = focus.asked_by_the_model([
        ToolCall(name="shopify_list_orders", args={}, ok=True, result={"orders": []}),
        ToolCall(name="asked_for", args={}, ok=True, result={"records": ["#1940", "gid://shopify/Order/1938"], "lists": ["shopify_list_orders"]}),
        ToolCall(name="asked_for", args={}, ok=False, error="refused"),
    ])
    assert said == focus.Asked(records=frozenset({"1940", "1938"}), lists=TODAY_S_ORDERS)
    assert focus.asked_by_the_model([ToolCall(name="shopify_list_orders", args={}, ok=True, result={})]) is None


async def test_the_tool_keeps_ids_and_list_kinds_and_changes_nothing():
    from app.tools import asked_for, gate, registry

    spec = registry.get("asked_for")
    assert spec.tier is gate.Tier.GREEN and spec.write is None and spec.batch is None
    assert "asked_for" in gate._KNOWN_TOOLS and not gate._looks_like_mutation("asked_for")
    out = await asked_for.asked_for(records=["#1940", "Priya Raman", "c28cf65d31fe6cbb", "#1940"], lists=["shopify_list_orders", "everything"])
    assert out == {"records": ["#1940", "c28cf65d31fe6cbb"], "lists": ["shopify_list_orders"],
                   "note": "Only ids and order numbers are kept; a name is not one. "
                           "A list is named by the read that drew it: its tool name, then the words you gave it."}
    assert await asked_for.asked_for() == {"records": [], "lists": []}


def test_cards_of_every_shape_are_read_and_a_failure_leaves_today_s_rules(monkeypatch):
    """A count where a list of rows usually is (a returns card's number of returns, a customer's
    number of orders) is no rows; and if choosing by what he asked for ever failed, DEC-069's rules
    would decide rather than the turn."""
    said = focus.Asked(records=frozenset({DAVIDS_THREAD}), lists=frozenset({("returns_stats", frozenset())}))
    stats = {"type": "returns", "data": {"view": "stats", "returns": 4, "rows": "none"}}
    count = {"type": "customer", "data": {"customer_id": data.DAVID.customer_id, "orders": 2, "history": {"recent": 3}}}
    drawn = [(stats, ToolCall(name="returns_stats", args={}, ok=True, result={}))]
    assert focus.answer_cards([HIS_EMAIL, stats, count], said=said, drawn=drawn) == [HIS_EMAIL, stats]

    def broken(*_a, **_k):
        raise ValueError("boom")

    monkeypatch.setattr(focus, "_as_asked", broken)
    cards = [INBOX, HIS_EMAIL, ORDER_1939]
    assert focus.answer_cards(cards, said=said) == focus.answer_cards(cards)
