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
  refused by `gmail_writes._about_this_order`, added in round 10: the right person, the wrong
  conversation, with a card claiming it answers the parcel she did not ask about;
* **a merely possible link** — her thread that names no order, while she has two recent orders
  — is refused too, as the deleted family refused it: "possible is never good enough to reply
  from". The same thread is replied in when it can only be about this order (her one recent
  order), or when the words the conversation was shown name it;
* the order cache is read through the thread card's own graph, so only a number that IS one of
  her orders counts — a year or somebody else's order number does not make a thread about a
  different order of hers — and a cold cache falls back to the narrow rule (this order's number
  in the thread), never upgrading a guess.
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
    FIRST: {"name": "Daniel Stub", "email": DANIEL, "label": "#1930"},
    SECOND: {"name": "Daniel Stub", "email": DANIEL, "label": "#1931"},
    SAMS: {"name": "Sam Other", "email": SAM, "label": "#1944"},
}


def _row(order_id: str) -> dict:
    who = ORDERS[order_id]
    digits = who["label"].lstrip("#")
    return {"order_id": order_id, "order_number": who["label"], "digits": digits, "ts": NOW, "created_at": "",
            "total": 60.0, "currency": "GBP", "fulfillment": "UNFULFILLED",
            "customer": {"customer_id": f"gid://shopify/Customer/{digits}", "name": who["name"], "email": who["email"]}}


class _Cache:
    def __init__(self, *, warm: bool, orders: tuple[str, ...] = tuple(ORDERS)) -> None:
        self.warm = warm
        self.orders = orders

    def rows(self) -> list[dict]:
        return [_row(o) for o in self.orders]

    def status(self) -> dict:
        return {"synced_at": NOW if self.warm else None, "orders": len(ORDERS)}


async def _customer_of(order_id: str, customer_id: str = "") -> dict:
    return dict(ORDERS[order_id])


@pytest.fixture()
def box():
    inbox = mailbox.FakeGmail()
    inbox.threads[HER_THREAD] = [mailbox.msg("m1", from_="Daniel Stub <daniel@example.com>", subject="Order 1930 — where is it?",
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
@pytest.mark.parametrize("tool", ["gmail_draft_reply", "gmail_send_reply"])
async def test_a_possible_link_is_never_replied_from(box, engine, session, tool):
    """What the deleted family called "possible": from her own address, naming no order, while
    she has two recent orders. Nothing says which one it is about, so a reply about #1931 is
    not prepared in it — before this round it was, with "#1931 · the customer on the order" on
    its card. The refusal says how to go on: without naming an order, or a new email."""
    box.threads[HER_THREAD][0]["headers"]["subject"] = "Quick question"
    text, proposal = await _reply(session, tool, HER_THREAD, SECOND)
    assert proposal is None, text
    assert "can't tell that thread is about order 1931" in text and "2 recent orders" in text, text
    assert "without naming an order" in text
    assert not box.drafts and not box.sent


@pytest.mark.usefixtures("owner_asking")
async def test_a_thread_that_can_only_be_about_her_one_recent_order_is_replied_in(box, engine, session, monkeypatch):
    """Her one recent order is #1931: a thread from her that names no order can only be about
    it, and neither a year nor somebody else's order number in its subject makes it a thread
    about a different order of hers."""
    monkeypatch.setattr(analytics_tools, "_cache", _Cache(warm=True, orders=(SECOND, SAMS)))
    for n, subject in enumerate(("Quick question", "Your 2026 lookbook", "Re: order 1944")):
        box.threads[HER_THREAD][0]["headers"]["subject"] = subject
        # The reply's own words name no order: since round 13 a reply that names Sam's #1944 to
        # Daniel is refused for that alone (tests/test_r13_reply_order_content.py), and what this
        # holds is the thread's subject, not the reply's words.
        text, proposal = await _reply(session, "gmail_draft_reply", HER_THREAD, SECOND, body=f"About your message ({n}).")
        assert proposal is not None, (subject, text)
        assert proposal.summary["order_line"] == "#1931 · the customer on the order"


@pytest.mark.usefixtures("owner_asking", "warm")
async def test_the_words_the_conversation_was_shown_can_name_the_order(box, engine, session):
    """The subject says nothing, but the thread this conversation read (the entity cache
    `gmail_read_thread` fills) has her asking about #1931 — that is a confident link, read off
    what the Mac already holds and never fetched for the purpose."""
    from app.memory import ENTITY
    from app.memory import current as memory

    box.threads[HER_THREAD][0]["headers"]["subject"] = "Quick question"
    memory().put(ENTITY, f"email_thread:{HER_THREAD}", {"thread_id": HER_THREAD, "messages": [
        {"from": "Daniel Stub", "from_email": DANIEL, "subject": "Quick question",
         "body": "Has order 1931 gone out yet?", "outbound": False},
    ]}, source="gmail")
    try:
        text, proposal = await _reply(session, "gmail_draft_reply", HER_THREAD, SECOND)
        assert proposal is not None, text
        text, proposal = await _reply(session, "gmail_draft_reply", HER_THREAD, FIRST)
        assert proposal is None and "That thread is about order 1931, not order 1930" in text, text
    finally:
        memory().drop(ENTITY, f"email_thread:{HER_THREAD}")


@pytest.mark.usefixtures("owner_asking")
async def test_a_cold_order_cache_falls_back_to_the_narrow_rule_and_never_upgrades_a_guess(box, engine, session, monkeypatch):
    """The replacement for test_graph's deleted cold-cache test. With nothing warm the Mac
    cannot tell her orders apart, so only this order's own number in the thread ties it to
    this order: another number is not this order, and no number at all is only possible —
    and neither is replied from. Another customer's thread is still refused on its
    recipient."""
    monkeypatch.setattr(analytics_tools, "_cache", _Cache(warm=False))
    text, proposal = await _reply(session, "gmail_draft_reply", HER_THREAD, FIRST)
    assert proposal is not None, "her thread naming this order is this order's thread"
    text, proposal = await _reply(session, "gmail_draft_reply", HER_THREAD, SECOND)
    assert proposal is None and "it names 1930, not 1931" in text, text
    box.threads[HER_THREAD][0]["headers"]["subject"] = "Quick question"
    text, proposal = await _reply(session, "gmail_draft_reply", HER_THREAD, SECOND)
    assert proposal is None and "does not name an order" in text, text
    text, proposal = await _reply(session, "gmail_draft_reply", SAMS_THREAD, FIRST)
    assert proposal is None and "not the customer on order #1930" in text, text
