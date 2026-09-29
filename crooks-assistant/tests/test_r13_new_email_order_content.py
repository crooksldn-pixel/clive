"""Round 13: a new email whose words name an order this conversation holds goes only to that
order's customer — the same rule the reply got, carried to `gmail_draft_new` and `gmail_send_new`.

The orders builder closed the reply (tests/test_r13_reply_order_content.py) and reported the
new email still open: an email to David, written from his own order or to an address the owner
dictated into a composer, could carry "#1938 is packed" — Mia's order, read a moment ago — with
nothing between it and David's inbox but the owner's hold. Now its subject and its words are read
for order numbers, and each one that is an order this conversation holds must belong to the
person it goes to, or nothing is prepared. That holds for fresh words, for the one draft waiting
in Gmail that `gmail_send_new` sends with no words, and for Send on the composer.

In the golden world (experience/fixtures): Mia Jones has #1938, David Randall has #1939. Every
sentence goes through the real `POST /turn` with the model's calls scripted as Claude would make
them; every tap through the real `POST /command`.
"""

from __future__ import annotations

import pytest

from experience.harness import harness
from tests import test_gmail_writes as mailbox
from tests import test_reply_order_binding as binding

DAVID = "david.randall@example.com"
SCOUT = "location.scout@example.org"


def _pending(h) -> list:
    return [p for p in h.runtime.sessions.get("s1").proposals if p.status.value == "PENDING"]


def _the_call(capture, name: str) -> dict:
    (call,) = [t for t in capture.raw.get("tool_calls") or [] if t.get("name") == name]
    return call


async def _holding_both_orders(h) -> tuple[dict, dict]:
    """He has looked at Mia's order and at David's, as he would on a busy morning."""
    mias = (await h.open_order(1938)).data("order")
    davids = (await h.open_order(1939)).data("order")
    assert (mias["order_number"], davids["order_number"]) == ("#1938", "#1939")
    return mias, davids


@pytest.mark.parametrize("tool", ["gmail_send_new", "gmail_draft_new"])
async def test_an_email_to_one_customer_naming_anothers_order_is_refused(tool):
    """The gap: David's own order as the recipient, Mia's order in the words. Before the repair
    this was prepared, addressed to David, and the hold card showed only David's order."""
    async with harness(admitted=True) as h:
        _mias, davids = await _holding_both_orders(h)
        said = await h.ask("email David that it's packed",
                           (tool, {"order_id": davids["order_id"], "subject": "Your order",
                                   "body": "Good news: #1938 is packed and goes out tomorrow."}))
        assert said.unmakeable == {}, said.unmakeable
        call = _the_call(said, tool)
        assert not call["ok"], call
        assert "1938" in call["error"] and DAVID in call["error"], call["error"]
        assert "Mia" not in call["error"], "the refusal does not say whose order it is"
        assert _pending(h) == [] and "confirmation" not in said.surface_types


@pytest.mark.parametrize("body", ["Good news: order1938 is packed.", "Good news: #\uff11\uff19\uff13\uff18 is packed."])
async def test_an_order_written_any_way_in_a_new_email_is_still_the_order_it_names(body):
    async with harness(admitted=True) as h:
        _mias, davids = await _holding_both_orders(h)
        said = await h.ask("email David", ("gmail_send_new", {"order_id": davids["order_id"], "subject": "Your order", "body": body}))
        call = _the_call(said, "gmail_send_new")
        assert not call["ok"] and "1938" in call["error"], (body, call)
        assert _pending(h) == []


async def test_the_subject_is_held_as_well_as_the_words():
    async with harness(admitted=True) as h:
        _mias, davids = await _holding_both_orders(h)
        said = await h.ask("email David", ("gmail_send_new", {"order_id": davids["order_id"],
                                                              "subject": "Order 1938", "body": "It went out today."}))
        call = _the_call(said, "gmail_send_new")
        assert not call["ok"] and "1938" in call["error"], call
        assert _pending(h) == []


@pytest.mark.parametrize("tool", ["gmail_send_new", "gmail_draft_new"])
async def test_an_email_naming_the_recipients_own_order_is_prepared(tool):
    """The control: David's own order, named in an email to David."""
    async with harness(admitted=True) as h:
        _mias, davids = await _holding_both_orders(h)
        said = await h.ask("email David", (tool, {"order_id": davids["order_id"], "subject": "Order #1939",
                                                  "body": "Your order #1939 went out today."}))
        assert _the_call(said, tool)["ok"], _the_call(said, tool)
        (proposal,) = _pending(h)
        assert proposal.execution["to"] == DAVID


async def test_an_email_from_the_composer_to_an_address_naming_a_held_order_is_refused():
    """Send on a composer he opened to an address he gave, with Mia's order in the words: not
    Mia's address, so not prepared. Through his own taps, the way the composer stages it."""
    async with harness(admitted=True) as h:
        await _holding_both_orders(h)
        opened = await h.ask("email the location scout",
                             ("gmail_compose_open", {"to": SCOUT, "subject": "Sunday",
                                                     "body": "Order 1938 is on the rail for the shoot."}))
        (composer,) = [i["data"] for i in opened.raw["ui"] if i["type"] == "email_compose"]
        ident = composer["compose_id"]
        typed = await h.touch("compose.field", compose_id=ident, field="to", value=SCOUT)
        assert typed.raw.get("ok"), typed.raw
        staged = await h.touch("compose.stage", compose_id=ident, mode="send")
        assert not staged.raw.get("ok"), staged.raw
        assert "1938" in str(staged.raw) and SCOUT in str(staged.raw), staged.raw
        assert _pending(h) == []


async def test_a_number_that_is_no_order_this_conversation_holds_is_not_taken_for_one():
    """Only orders this conversation was shown count: a number nobody looked up is words."""
    async with harness(admitted=True) as h:
        davids = (await h.open_order(1939)).data("order")
        said = await h.ask("email David", ("gmail_send_new", {"order_id": davids["order_id"], "subject": "Your order",
                                                              "body": "The label starts 1938; it went out today."}))
        assert _the_call(said, "gmail_send_new")["ok"], _the_call(said, "gmail_send_new")
        assert len(_pending(h)) == 1


# ============================================================ the draft that is already waiting
#
# `gmail_send_new` with no words sends the one draft waiting for that customer, as Gmail holds
# it. Those words are held the same way. The in-memory mailbox of tests/test_gmail_writes.py and
# the orders of tests/test_reply_order_binding.py: Daniel has #1930, Sam has #1944.

box, engine, warm, session = binding.box, binding.engine, binding.warm, binding.session


@pytest.mark.usefixtures("owner_asking", "warm")
async def test_a_waiting_draft_that_names_another_customers_order_is_not_sent(box, engine, session):
    """A draft to Sam, written in Gmail, that tells him Daniel's #1930 went out: not sent to Sam."""
    from app.tools import gmail_writes
    from app.tools.dispatch import dispatch

    raw = gmail_writes.build_raw(sender=mailbox.ME, sender_name="CROOKS", to=binding.SAM, to_name="Sam Other",
                                 subject="Your order", body="Your order #1930 went out today.",
                                 token="<draft-2@crooksldn.com>")
    box.create_draft(raw, None)
    before = len(session.proposals)
    text = await dispatch("gmail_send_new", {"order_id": binding.SAMS}, session=session, timeout_s=5)
    assert len(session.proposals) == before, text
    assert "names order 1930" in text and binding.SAM in text, text
    assert not box.sent


@pytest.mark.usefixtures("owner_asking", "warm")
async def test_a_waiting_draft_naming_the_customers_own_order_is_offered_to_send(box, engine, session):
    """The control on the same mailbox: Sam's own #1944 in the draft to Sam."""
    from app.tools import gmail_writes
    from app.tools.dispatch import dispatch

    raw = gmail_writes.build_raw(sender=mailbox.ME, sender_name="CROOKS", to=binding.SAM, to_name="Sam Other",
                                 subject="Your order", body="Your order #1944 went out today.",
                                 token="<draft-3@crooksldn.com>")
    box.create_draft(raw, None)
    before = len(session.proposals)
    text = await dispatch("gmail_send_new", {"order_id": binding.SAMS}, session=session, timeout_s=5)
    assert len(session.proposals) == before + 1, text
    assert session.proposals[-1].execution["to"] == binding.SAM
