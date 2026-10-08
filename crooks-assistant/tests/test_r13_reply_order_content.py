"""Round 13: a reply whose words name an order this conversation holds goes only to that
order's customer, whether or not the model said which order it was about.

The round-12 deploy review, R9-E-families1-E-04 and R9-I-tests3-I-02. `gmail_send_reply` and
`gmail_draft_reply` hold a reply to an order only when the model passes `order_id`. Leave it
out and nothing is checked: "Your order #1938 went out today" — Mia's order, read a moment ago —
placed in David's thread is prepared, addressed to David, and the hold card has no order line
and says the reply goes to whoever wrote last. The owner's hold was the only guard between one
customer's order and another customer's inbox.

Now the words the reply carries are read for order numbers, and each one that is an order this
conversation holds must belong to the person the reply goes to, or nothing is prepared.

In the golden world (experience/fixtures): Mia Jones has #1938, David Replica has #1939 and a
thread asking where it is. Every sentence goes through the real `POST /turn`, with the model's
calls scripted as Claude would make them.
"""

from __future__ import annotations

import pytest

from experience.harness import harness
from tests import test_gmail_writes as mailbox
from tests import test_reply_order_binding as binding

DAVIDS_THREAD = "58361c4d87dfeee5"
MIAS_THREAD = "aa70d3f83dbef06e"


def _pending(h) -> list:
    return [p for p in h.runtime.sessions.get("s1").proposals if p.status.value == "PENDING"]


def _the_call(capture, name: str) -> dict:
    (call,) = [t for t in capture.raw.get("tool_calls") or [] if t.get("name") == name]
    return call


async def _holding_mias_order_and_davids_thread(h) -> dict:
    """He looks at Mia's order, then at David's email, as he would before answering it."""
    order = await h.open_order(1938)
    assert order.data("order")["order_number"] == "#1938"
    found = await h.ask("anything from David about 1939?", ("gmail_search", {"query": "1939", "days": 7}),
                        ("gmail_read_thread", {"thread_id": DAVIDS_THREAD}))
    assert found.unmakeable == {}, found.unmakeable
    return order.data("order")


@pytest.mark.parametrize("tool", ["gmail_send_reply", "gmail_draft_reply"])
async def test_a_reply_naming_another_customers_order_is_refused_without_order_id(tool):
    """The finding's own case: Mia's order number in a reply in David's thread, no `order_id`.
    Before the repair this was prepared, addressed to David."""
    async with harness(admitted=True) as h:
        await _holding_mias_order_and_davids_thread(h)
        said = await h.ask("tell him it went out today",
                           (tool, {"thread_id": DAVIDS_THREAD, "body": "Your order #1938 went out today."}))
        assert said.unmakeable == {}, said.unmakeable
        call = _the_call(said, tool)
        assert not call["ok"], call
        assert "1938" in call["error"] and "david.replica@example.com" in call["error"], call["error"]
        assert "Mia" not in call["error"], "the refusal does not say whose order it is"
        assert _pending(h) == [] and "confirmation" not in said.surface_types


async def test_a_bare_number_that_is_a_held_order_counts_as_well():
    async with harness(admitted=True) as h:
        await _holding_mias_order_and_davids_thread(h)
        said = await h.ask("reply", ("gmail_send_reply", {"thread_id": DAVIDS_THREAD,
                                                          "body": "Sorry for the wait. 1938 is on its way."}))
        assert not _the_call(said, "gmail_send_reply")["ok"] and _pending(h) == []


@pytest.mark.parametrize("body", [
    "Your order1938 went out today to 12 Acacia Avenue.",   # a letter right before the number
    "Your order #\uff11\uff19\uff13\uff18 went out today.",  # full-width digits
    "Your order #19\u200b38 went out today.",               # a zero-width space inside it
    "Your order No.1938 went out today.",
])
async def test_an_order_written_any_way_is_still_the_order_it_names(body):
    """The round-13 independent check: the order pattern the thread card uses refuses a number
    with a letter before it, and reads full-width digits that the held order's number never
    equals, so these were prepared to David. Written any way, #1938 is Mia's."""
    async with harness(admitted=True) as h:
        await _holding_mias_order_and_davids_thread(h)
        said = await h.ask("reply", ("gmail_send_reply", {"thread_id": DAVIDS_THREAD, "body": body}))
        call = _the_call(said, "gmail_send_reply")
        assert not call["ok"] and "1938" in call["error"], (body, call)
        assert _pending(h) == []


async def test_money_and_longer_numbers_are_not_taken_for_a_held_order():
    """Only whole runs of digits: "£19.38" is not #1938, nor is "19380"."""
    async with harness(admitted=True) as h:
        await _holding_mias_order_and_davids_thread(h)
        said = await h.ask("reply", ("gmail_send_reply", {"thread_id": DAVIDS_THREAD,
                                                          "body": "We refunded £19.38; the parcel ref is 19380."}))
        assert _the_call(said, "gmail_send_reply")["ok"], _the_call(said, "gmail_send_reply")


async def test_naming_the_right_order_does_not_let_the_words_name_another(tool="gmail_send_reply"):
    """`order_id` given — David's own #1939, which passes the thread's own check — and the words
    carry Mia's #1938 as well. The words are held too."""
    async with harness(admitted=True) as h:
        await _holding_mias_order_and_davids_thread(h)
        davids = (await h.open_order(1939)).data("order")
        said = await h.ask("reply", (tool, {"thread_id": DAVIDS_THREAD, "order_id": davids["order_id"],
                                            "body": "1939 went out, and #1938 is packed."}))
        call = _the_call(said, tool)
        assert not call["ok"] and "1938" in call["error"], call
        assert _pending(h) == []


async def test_a_reply_naming_the_recipients_own_order_is_prepared():
    """The control: David's own order, named in his own thread, with no `order_id`."""
    async with harness(admitted=True) as h:
        await _holding_mias_order_and_davids_thread(h)
        await h.open_order(1939)
        said = await h.ask("reply", ("gmail_send_reply", {"thread_id": DAVIDS_THREAD,
                                                          "body": "Your order #1939 went out yesterday."}))
        assert _the_call(said, "gmail_send_reply")["ok"], _the_call(said, "gmail_send_reply")
        (proposal,) = _pending(h)
        assert proposal.execution["to"] == "david.replica@example.com"


async def test_a_number_that_is_no_order_this_conversation_holds_is_not_taken_for_one():
    """A reply that says "£1938" worth of something, or quotes a number nobody looked up, is not
    held to an order: only orders this conversation was shown count."""
    async with harness(admitted=True) as h:
        await h.ask("anything from David?", ("gmail_search", {"query": "1939", "days": 7}),
                    ("gmail_read_thread", {"thread_id": DAVIDS_THREAD}))
        said = await h.ask("reply", ("gmail_send_reply", {"thread_id": DAVIDS_THREAD,
                                                          "body": "Tracking starts 1938 on the label; it went out."}))
        assert _the_call(said, "gmail_send_reply")["ok"]
        assert len(_pending(h)) == 1


# ============================================================ the draft that is already waiting
#
# `gmail_send_reply` with no words sends the one draft waiting in the thread, as Gmail holds it.
# Those words are held the same way: a draft someone wrote in Gmail naming another customer's
# order is not sent to this one. The in-memory mailbox of tests/test_gmail_writes.py, and the
# orders of tests/test_reply_order_binding.py: Daniel has #1930, Sam has #1944.

box, engine, warm, session = binding.box, binding.engine, binding.warm, binding.session


@pytest.mark.usefixtures("owner_asking", "warm")
async def test_a_waiting_draft_that_names_another_customers_order_is_not_sent(box, engine, session):
    from app.tools import gmail_writes

    raw = gmail_writes.build_raw(sender=mailbox.ME, sender_name="CROOKS", to=binding.SAM, to_name="Sam Other",
                                 subject="Re: Order 1930 — is this mine?", body="Your order #1930 went out today.",
                                 token="<draft-1@crooksldn.com>", in_reply_to="<sam@example.com>")
    box.create_draft(raw, binding.SAMS_THREAD)
    text, proposal = await binding._reply(session, "gmail_send_reply", binding.SAMS_THREAD, "", body="")
    assert proposal is None, text
    assert "names order 1930" in text and binding.SAM in text, text
    assert not box.sent


@pytest.mark.usefixtures("owner_asking", "warm")
async def test_a_waiting_draft_whose_own_subject_names_another_customers_order_is_not_sent(box, engine, session):
    """The waiting draft's subject is held as well as its words, unless it is the thread's own:
    a subject someone typed in Gmail naming Daniel's #1930 does not go to Sam."""
    from app.tools import gmail_writes

    raw = gmail_writes.build_raw(sender=mailbox.ME, sender_name="CROOKS", to=binding.SAM, to_name="Sam Other",
                                 subject="Order 1930 is on its way", body="It went out today.",
                                 token="<draft-4@crooksldn.com>", in_reply_to="<sam@example.com>")
    box.create_draft(raw, binding.SAMS_THREAD)
    text, proposal = await binding._reply(session, "gmail_send_reply", binding.SAMS_THREAD, "", body="")
    assert proposal is None, text
    assert "names order 1930" in text and binding.SAM in text, text
    assert not box.sent
