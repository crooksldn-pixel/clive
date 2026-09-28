"""A reply about one order goes into that order's customer's thread, and not into another's.

The 2026-09-28 deploy review, round 9, E-04 and I-tests3 I-02. The deleted order→email family
(`order_email._choose`) refused a merely possible order→thread link before it armed a reply,
and `test_graph.py` lost the assertions that held it. Every reply is now the model's: it picks
the thread and names the order, and `gmail_draft_reply`/`gmail_send_reply` prepare it. What
stops a reply about one customer's order landing in someone else's thread is therefore the
write tool's own check, and these hold it on the live path — `dispatch`, the gate and the
action engine, exactly as the model's tool call arrives:

* **another customer's thread** — including one that NAMES this order, the possible link the
  old family refused — is refused by `gmail_writes._check_order`: the reply would go to the
  thread's sender, and the sender is not the customer on the order. This was already true of
  the model path; it had no test that said so;
* **another of the same customer's orders** — her thread about #1930, a reply about #1931 — is
  refused by `gmail_writes._another_of_theirs`, added in round 10: the right person, the wrong
  conversation, with a card claiming it answers the parcel she did not ask about. It reads the
  order cache through the thread card's own graph, so only a number that IS one of her orders
  counts, and a cold cache falls back to the recipient check alone rather than guessing;
* a thread from the customer that names no order is hers and is not about a different order:
  the reply is prepared, and its card names the recipient as the customer on the order, which
  is the one thing that was checked.
"""

from __future__ import annotations

import pytest

from app.session.models import Session
from app.tools import analytics_tools, gmail_writes
from app.tools.dispatch import dispatch
from tests import test_gmail_writes as mailbox

NOW = 1_800_000_000.0
DANIEL, SAM = mailbox.CUSTOMER, "sam.other@example.com"
FIRST, SECOND = "gid://shopify/Order/1930", "gid://shopify/Order/1931"
SAMS = "gid://shopify/Order/1944"
HER_THREAD, SAMS_THREAD = mailbox.THREAD, "18f3a9c2b1d4e5f7"

ORDERS = {
    FIRST: {"name": "Daniel Sear", "email": DANIEL, "label": "#1930"},
    SECOND: {"name": "Daniel Sear", "email": DANIEL, "label": "#1931"},
    SAMS: {"name": "Sam Other", "email": SAM, "label": "#1944"},
}


def _row(order_id: str) -> dict:
    who = ORDERS[order_id]
    digits = who["label"].lstrip("#")
    return {"order_id": order_id, "order_number": who["label"], "digits": digits, "ts": NOW, "created_at": "",
            "total": 60.0, "currency": "GBP", "fulfillment": "UNFULFILLED",
            "customer": {"customer_id": f"gid://shopify/Customer/{digits}", "name": who["name"], "email": who["email"]}}


class _Cache:
    def __init__(self, *, warm: bool) -> None:
        self.warm = warm

    def rows(self) -> list[dict]:
        return [_row(o) for o in ORDERS]

    def status(self) -> dict:
        return {"synced_at": NOW if self.warm else None, "orders": len(ORDERS)}


async def _customer_of(order_id: str, customer_id: str = "") -> dict:
    return dict(ORDERS[order_id])


@pytest.fixture()
def box():
    inbox = mailbox.FakeGmail()
    inbox.threads[HER_THREAD] = [mailbox.msg("m1", from_="Daniel Sear <daniel@example.com>", subject="Order 1930 — where is it?",
                                             mid="<abc@example.com>", labels=["INBOX"])]
    inbox.threads[SAMS_THREAD] = [mailbox.msg("s1", from_="Sam Other <sam.other@example.com>", subject="Order 1930 — is this mine?",
                                              mid="<sam@example.com>", labels=["INBOX"])]
    gmail_writes.bind(inbox, customer=_customer_of, policy=lambda: mailbox.Policy())
    yield inbox
    gmail_writes.bind(None)


engine = mailbox.engine


@pytest.fixture()
def warm(monkeypatch):
    monkeypatch.setattr(analytics_tools, "_cache", _Cache(warm=True))


@pytest.fixture()
def session() -> Session:
    s = Session(session_id="bind2")
    s.issue(FIRST, SECOND, SAMS, HER_THREAD, SAMS_THREAD)
    s.epoch = 1
    return s


async def _reply(session, tool: str, thread_id: str, order_id: str, body: str = "It ships tomorrow."):
    before = len(session.proposals)
    text = await dispatch(tool, {"thread_id": thread_id, "order_id": order_id, "body": body},
                          session=session, timeout_s=5)
    return text, (session.proposals[-1] if len(session.proposals) > before else None)


@pytest.mark.usefixtures("owner_asking", "warm")
@pytest.mark.parametrize("tool", ["gmail_draft_reply", "gmail_send_reply"])
async def test_a_reply_about_one_customers_order_is_refused_in_another_customers_thread(box, engine, session, tool):
    """Sam's thread NAMES order 1930 — the "possible" link the deleted family never replied
    from. A reply about #1930 would go to Sam, who is not its customer: refused, nothing made."""
    text, proposal = await _reply(session, tool, SAMS_THREAD, FIRST)
    assert proposal is None, text
    assert "would go to sam.other@example.com, not the customer on order #1930" in text, text
    assert not box.drafts and not box.sent


@pytest.mark.usefixtures("owner_asking", "warm")
@pytest.mark.parametrize("tool", ["gmail_draft_reply", "gmail_send_reply"])
async def test_her_thread_about_one_order_is_not_the_thread_for_another_of_hers(box, engine, session, tool):
    """Two orders, one customer: her thread is about #1930, the reply is about #1931. Before
    round 10 this was prepared with "#1931 · the customer on the order" on its card."""
    text, proposal = await _reply(session, tool, HER_THREAD, SECOND)
    assert proposal is None, text
    assert "That thread is about order 1930, not order 1931" in text, text
    assert not box.drafts and not box.sent


@pytest.mark.usefixtures("owner_asking", "warm")
async def test_the_thread_that_is_about_the_order_is_replied_in(box, engine, session):
    """The control: the same customer, the same thread, the order it is about."""
    text, proposal = await _reply(session, "gmail_draft_reply", HER_THREAD, FIRST)
    assert proposal is not None and proposal.status.value == "PENDING", text
    assert proposal.execution["to"] == DANIEL
    assert proposal.summary["order_line"] == "#1930 · the customer on the order"


@pytest.mark.usefixtures("owner_asking", "warm")
async def test_a_number_that_is_not_one_of_hers_does_not_make_it_another_orders_thread(box, engine, session):
    """A year in a subject is four digits and no order of hers; Sam's order is an order, and
    not hers. Neither says her thread is about a different order of hers."""
    for subject in ("Your 2026 lookbook", "Re: order 1944"):
        box.threads[HER_THREAD][0]["headers"]["subject"] = subject
        text, proposal = await _reply(session, "gmail_draft_reply", HER_THREAD, SECOND, body=f"About {subject}.")
        assert proposal is not None, (subject, text)


@pytest.mark.usefixtures("owner_asking", "warm")
async def test_her_thread_that_names_no_order_is_hers_to_be_replied_in(box, engine, session):
    """What the deleted family called "possible" — from her own address, naming no order — is
    not a different order's thread. The recipient is proven to be the order's customer, and
    that is what the card says; nothing claims the thread was about the order."""
    box.threads[HER_THREAD][0]["headers"]["subject"] = "Quick question"
    text, proposal = await _reply(session, "gmail_draft_reply", HER_THREAD, SECOND)
    assert proposal is not None, text
    assert proposal.summary["order_line"] == "#1931 · the customer on the order"


@pytest.mark.usefixtures("owner_asking")
async def test_a_cold_order_cache_never_upgrades_a_guess(box, engine, session, monkeypatch):
    """The replacement for test_graph's deleted cold-cache test. With nothing warm, the Mac
    cannot tell whether "1930" is one of her orders, so it does not refuse on that ground —
    and it does not decide anything else from it either: the recipient check alone stands, and
    another customer's thread is still refused."""
    monkeypatch.setattr(analytics_tools, "_cache", _Cache(warm=False))
    text, proposal = await _reply(session, "gmail_draft_reply", HER_THREAD, SECOND)
    assert proposal is not None, text
    text, proposal = await _reply(session, "gmail_draft_reply", SAMS_THREAD, FIRST)
    assert proposal is None and "not the customer on order #1930" in text, text
