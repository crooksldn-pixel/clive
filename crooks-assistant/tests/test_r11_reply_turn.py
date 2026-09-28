"""A reply about one order is prepared only in a thread confidently about that order — held on the
model's own path, from the sentence to the screen.

The 2026-09-28 deploy review, round 9, E-04 (E-families1) and I-tests3 I-02, still unsettled in
round 10 because the reviewing parts held neither `app/tools/gmail_writes.py` nor the model path.
Round 10 put the refusal on the write tool itself (`gmail_writes._check_order`, which asks
`_about_this_order`) and held it through `dispatch` (tests/test_reply_order_binding.py). These go
one step further out: the sentence goes to `POST /turn`, the harness's model makes the reply call
as Claude would — through the same dispatcher, gate and action engine the provider hands every
tool call to (`app/providers/max_agent_sdk.py::_dispatch` passes the model's arguments to
`dispatch` unchanged; `app/routes/turn.py` prepares no reply of its own) — and what is asserted is
what the Mac does with that call: whether a card reaches the glass, whether a proposal waits,
and what the model is told.

The golden world has the case in it already: Mia Jones has two recent orders, #1938 (today) and
#1912 (six weeks ago), and a thread about each. Reading #1938 shows the conversation both orders
and both threads, so every id below is one the gate has seen issued — nothing is granted to the
test from outside the conversation:

* her thread about #1938 is not the thread for a reply about #1912, and her thread about #1912
  is not the thread for a reply about #1938 — the right person, the wrong conversation;
* a thread from her that names no order, while she has two recent ones, is only POSSIBLY about
  either, and is not replied from ("possible is never good enough to reply from");
* the thread that IS about the order is replied in, and the card names the order.
"""

from __future__ import annotations

import pytest

from experience.fixtures import data
from experience.harness import harness

HER_1938_THREAD = "aa70d3f83dbef06e"     # "Order 1938 — can I add to it?"
HER_1912_THREAD = "fe128e8f1ec5a51e"     # "Order 1912 arrived"
ORDER_1938 = data.BY_NAME["#1938"].order_id
ORDER_1912 = data.BY_NAME["#1912"].order_id


@pytest.fixture()
async def stage():
    async with harness(admitted=True) as h:
        yield h


async def _shown_mias_orders(h, session: str) -> None:
    """"Show me order 1938", and the two reads Claude makes for it. The order read carries her
    history and her email, which is how the conversation comes to hold both orders and both
    threads."""
    await h.open_order("1938", session_id=session)
    held = h.runtime.sessions.get(session).issued_ids
    assert {ORDER_1938, ORDER_1912, HER_1938_THREAD, HER_1912_THREAD} <= set(held), sorted(held)


async def _reply(h, session: str, tool: str, thread_id: str, order_id: str):
    said = await h.ask(f"reply to Mia about that order ({tool}, {thread_id[-4:]}, {order_id[-4:]})",
                       (tool, {"thread_id": thread_id, "order_id": order_id, "body": "It went out this morning."}),
                       session_id=session)
    made = [c for c in said.raw.get("tool_calls") or [] if c.get("name") == tool]
    assert len(made) == 1, said.raw.get("tool_calls")
    return said, made[0]


def _nothing_prepared(h, session: str, said) -> None:
    held = h.runtime.sessions.get(session)
    assert not [p for p in held.proposals if p.status.value == "PENDING"], [(p.operation, p.status.value) for p in held.proposals]
    assert not said.surface("confirmation"), said.surface_types
    assert getattr(h.store, "mutations_sent", -1) == 0


@pytest.mark.parametrize("tool", ["gmail_draft_reply", "gmail_send_reply"])
@pytest.mark.parametrize(("thread_id", "order_id", "about"), [
    (HER_1938_THREAD, ORDER_1912, "That thread is about order 1938, not order 1912"),
    (HER_1912_THREAD, ORDER_1938, "That thread is about order 1912, not order 1938"),
], ids=["her-1938-thread-for-1912", "her-1912-thread-for-1938"])
async def test_her_thread_about_one_order_is_refused_for_a_reply_about_the_other(stage, tool, thread_id, order_id, about):
    """Two orders, one customer, a spoken turn: the model names the other order. The write tool
    refuses; no card reaches the screen; the model is told why and how to go on."""
    session = f"r11rt-{tool[-5:]}-{thread_id[-3:]}"
    await _shown_mias_orders(stage, session)
    said, call = await _reply(stage, session, tool, thread_id, order_id)
    assert call["ok"] is False and call.get("proposal_id") is None, call
    assert about in str(call.get("error")), call
    assert "Nothing was prepared" in str(call.get("error"))
    _nothing_prepared(stage, session, said)


@pytest.mark.parametrize("tool", ["gmail_draft_reply", "gmail_send_reply"])
async def test_a_thread_only_possibly_about_this_order_is_refused(stage, monkeypatch, tool):
    """Her thread names no order, and she has two recent ones: it could be about either. The
    deleted order→email family never replied from a possible link; the model's path does not
    either."""
    message = data.BY_THREAD[HER_1938_THREAD].messages[0]
    monkeypatch.setattr(message, "subject", "Quick question")
    monkeypatch.setattr(message, "body", "Is it too late to add a cap? Thanks, Mia.")
    session = f"r11rt-possible-{tool[-5:]}"
    await _shown_mias_orders(stage, session)
    said, call = await _reply(stage, session, tool, HER_1938_THREAD, ORDER_1938)
    assert call["ok"] is False and call.get("proposal_id") is None, call
    assert "can't tell that thread is about order 1938" in str(call.get("error")), call
    assert "without naming an order" in str(call.get("error"))
    _nothing_prepared(stage, session, said)


async def test_the_thread_that_is_about_the_order_is_replied_in(stage):
    """The control: her thread about #1938, a reply about #1938. It is prepared — a card waiting
    for the owner's tap, naming the order and addressed to her — and nothing is sent."""
    session = "r11rt-control"
    await _shown_mias_orders(stage, session)
    said, call = await _reply(stage, session, "gmail_draft_reply", HER_1938_THREAD, ORDER_1938)
    assert call["ok"] is True and call.get("proposal_id"), call
    (proposal,) = [p for p in stage.runtime.sessions.get(session).proposals if p.status.value == "PENDING"]
    assert proposal.execution["to"] == data.MIA.email and proposal.execution["thread_id"] == HER_1938_THREAD
    assert proposal.summary["order_line"] == "#1938 · the customer on the order"
    assert said.surface("confirmation"), said.surface_types
    assert getattr(stage.store, "mutations_sent", -1) == 0
