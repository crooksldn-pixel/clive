"""Ruling 27 (DEC-071): archive or junk a set of threads on ONE card and ONE hold.

Junk is Gmail's own "Report spam": a staged write per thread (gmail_thread_junk), each checked on
its own and proven by reading its labels back, held together by the batch engine under one card
(batch_email_junk). It is RED, so even one thread is a hold, and it is never done to a customer of
the shop. The card names every thread that will change and every one left out, with why; after the
hold each thread is said with what became of it, and a failure is said per thread. The inbox is a
fake in memory; nothing reaches a network."""

from __future__ import annotations

import pytest

from app.actions import batch as batch_module
from app.actions import engine as engine_module
from app.actions.batch import BatchEngine
from app.actions.engine import ActionEngine
from app.actions.grammar import gesture_for
from app.actions.ledger import NullLedger
from app.analytics import sets
from app.presentation import present, present_batch_state
from app.session.models import Session
from app.tools import gmail_tools, gmail_writes, registry
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_batch import gesture
from tests.test_gmail_writes import FakeGmail, Policy, msg

pytestmark = pytest.mark.usefixtures("owner_asking")

SPAMMY = {
    "18f00000000000a1": [msg("a1", from_="Promo Bot <deals@example.net>", subject="WIN A PRIZE", mid="<p1@x>", labels=["INBOX", "UNREAD"])],
    "18f00000000000a2": [msg("a2", from_="SEO Expert <seo@example.org>", subject="Rank #1 on Google", mid="<p2@x>", labels=["INBOX"])],
    "18f00000000000a3": [msg("a3", from_="Ana Fixture <ana@example.com>", subject="Where is my order?", mid="<p3@x>", labels=["INBOX"])],
    "18f00000000000a4": [msg("a4", from_="Old Spam <old@example.net>", subject="Already junk", mid="<p4@x>", labels=["SPAM"])],
}
CUSTOMERS = {"ana@example.com"}


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


@pytest.fixture()
def batches(engine, monkeypatch):
    b = BatchEngine(engine)
    monkeypatch.setattr(batch_module, "_batches", b)
    return b


@pytest.fixture()
def session():
    s = Session(session_id="j1")
    s.epoch = 1
    s.turn_id = "turn_j"
    return s


@pytest.fixture()
def box(monkeypatch):
    inbox = FakeGmail()
    inbox.threads = {tid: [dict(m, labels=list(m["labels"])) for m in ms] for tid, ms in SPAMMY.items()}
    gmail_writes.bind(inbox, policy=lambda: Policy())

    async def known(email: str) -> bool:
        return email in CUSTOMERS

    monkeypatch.setattr(gmail_tools, "_customer_lookup", known)
    yield inbox
    gmail_writes.bind(None)


async def stage(session, tool, **args):
    """A batch tool called as the turn calls it: through the dispatcher and the gate."""
    calls: list = []
    text = await dispatch(tool, args, session=session, timeout_s=10, calls=calls)
    batch = session.batches[calls[-1].proposal_id] if calls and calls[-1].proposal_id else None
    return text, batch, calls


async def stage_one(session, tool, **args):
    """One write called as the turn calls it: staged as a proposal, nothing sent."""
    before = len(session.proposals)
    text = await dispatch(tool, args, session=session, timeout_s=5)
    return text, (session.proposals[-1] if len(session.proposals) > before else None)


def a_set(session, members=None):
    ids = members or list(SPAMMY)
    return sets.create(session, kind="emails", members=ids, label="email: today",
                       labels={tid: SPAMMY[tid][0]["headers"]["subject"] for tid in ids})


# ------------------------------------------------------------------------- declaration


def test_junk_is_a_reviewed_reversible_write_held_even_for_one_thread():
    spec = registry.get("gmail_thread_junk")
    assert spec.tier is Tier.RED and spec.write.complete and spec.write.kind == "reversible" and spec.write.mutation == "gmail:labels"
    assert gesture_for("RED", "reversible") == "hold_to_arm", "one thread is still a hold: Gmail learns from a junk"
    assert spec.issued_id_args == ("thread_id",)
    assert classify("gmail_thread_junk", {"thread_id": "18f00000000000a1"}, issued_ids={"18f00000000000a1"}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify("gmail_thread_junk", {"thread_id": "18f00000000000a1"}).disposition is Disposition.DENY, "an unissued thread"
    batch = registry.get("batch_email_junk")
    assert batch.tier is Tier.RED and batch.batch.complete and batch.batch.child_tool == "gmail_thread_junk" and batch.write is None
    assert batch.issued_id_args == ("set_id",) and batch.batch.set_kinds == ("emails",)
    assert classify("batch_email_junk", {"set_id": "set_abcdef123456"}, issued_ids={"set_abcdef123456"}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify("batch_email_junk", {"set_id": "set_abcdef123456"}).disposition is Disposition.DENY


# ------------------------------------------------------------------------- one card, one hold


async def test_a_set_is_junked_on_one_card_and_one_hold_and_each_thread_is_read_back(engine, batches, session, box):
    ws = a_set(session)
    text, batch, calls = await stage(session, "batch_email_junk", set_id=ws.set_id)
    assert batch is not None and batch.interaction == "hold_to_arm", "one hold, however few"
    assert [c.label for c in batch.eligible] == ["WIN A PRIZE", "Rank #1 on Google"]
    left_out = {c.label: c.excluded for c in batch.excluded}
    assert left_out["Where is my order?"].startswith("from a customer of the shop"), left_out
    assert left_out["Already junk"] == "already in Spam", left_out
    card = present(calls, session=session)[0]
    assert card["type"] == "batch_action"
    data = card["data"]
    assert data["title"] == "Junk 2 threads" and data["members"] == ["WIN A PRIZE", "Rank #1 on Google"], "the card lists what will change"
    assert {e["label"] for e in data["excluded"]} == {"Where is my order?", "Already junk"}, "and what will not, with why"
    assert "Gmail learns from it" in data["detail"] and data["interaction"]["kind"] == "hold_to_arm"
    assert not [c for c in box.calls if c[0] == "modify"], "nothing changes before the hold"

    result = await gesture(batches, batch)
    assert result.spoken == "Junked 2 of the 2 threads."
    for tid in ("18f00000000000a1", "18f00000000000a2"):
        labels = box.thread_labels(tid)
        assert "SPAM" in labels and "INBOX" not in labels
    assert "INBOX" in box.thread_labels("18f00000000000a3"), "the customer's email is untouched"
    rows = present_batch_state(batch, session=session)[0]["data"]["rows"]
    assert {r["label"]: r["outcome"] for r in rows if r["code"] != "excluded"} == {"WIN A PRIZE": "applied", "Rank #1 on Google": "applied"}

    undo = session.batches[batch.undo_id]
    back = await gesture(batches, undo)
    assert back.code == "done"
    for tid in ("18f00000000000a1", "18f00000000000a2"):
        labels = box.thread_labels(tid)
        assert "INBOX" in labels and "SPAM" not in labels, "Not spam: back in the inbox"


async def test_a_thread_that_fails_is_said_by_name_and_the_rest_still_count(engine, batches, session, box):
    ws = a_set(session, ["18f00000000000a1", "18f00000000000a2"])
    _, batch, _ = await stage(session, "batch_email_junk", set_id=ws.set_id)
    real = box.modify_thread

    def refuse_one(thread_id, *, add, remove):
        if thread_id == "18f00000000000a2":
            box.calls.append(("modify", thread_id, tuple(add), tuple(remove)))
            raise gmail_writes.GmailError("Could not change the thread's labels: refused")
        return real(thread_id, add=add, remove=remove)

    box.modify_thread = refuse_one
    result = await gesture(batches, batch)
    assert result.spoken.startswith("Junked 1 of the 2 threads.") and ("could not be applied" in result.spoken or "could not be confirmed" in result.spoken)
    data = present_batch_state(batch, session=session)[0]["data"]
    by_name = {r["label"]: r["outcome"] for r in data["rows"]}
    assert by_name["WIN A PRIZE"] == "applied" and by_name["Rank #1 on Google"] != "applied", by_name
    assert data["title"] == "Junked: 1 of 2" and data["all_verified"] is False
    assert "check them in Gmail" in data["note"], "a Gmail batch sends him to Gmail, not Shopify"
    assert "INBOX" in box.thread_labels("18f00000000000a2"), "the refused one was left as it was"


async def test_a_thread_moved_since_the_card_is_left_alone_and_said_so(engine, batches, session, box):
    ws = a_set(session, ["18f00000000000a1", "18f00000000000a2"])
    _, batch, _ = await stage(session, "batch_email_junk", set_id=ws.set_id)
    box.modify_thread("18f00000000000a2", add=[], remove=["INBOX"])   # archived in Gmail meanwhile
    result = await gesture(batches, batch)
    assert result.spoken == "Junked 1 of the 2 threads. 1 changed meanwhile and was left alone."
    assert "SPAM" not in box.thread_labels("18f00000000000a2")


async def test_a_set_with_only_customers_is_refused_before_any_card(engine, batches, session, box):
    ws = a_set(session, ["18f00000000000a3"])
    text, batch, _ = await stage(session, "batch_email_junk", set_id=ws.set_id)
    assert batch is None and text.startswith("ERROR") and "from a customer of the shop" in text


async def test_a_sender_the_shop_could_not_be_asked_about_is_not_junked(engine, batches, session, box, monkeypatch):
    async def down(email: str) -> bool:
        raise RuntimeError("Shopify is down")

    monkeypatch.setattr(gmail_tools, "_customer_lookup", down)
    ws = a_set(session, ["18f00000000000a1"])
    text, batch, _ = await stage(session, "batch_email_junk", set_id=ws.set_id)
    assert batch is None and "could not be checked against the shop's customers" in text, "unknown is RED"


# ------------------------------------------------------------------------- one thread


async def hold_one(engine, proposal):
    armed, code = engine.arm(proposal.proposal_id, proposal.session_id)
    assert code == "", code
    proposal.armed_at -= 1.0
    return await engine.commit(proposal.proposal_id, proposal.session_id, caller="o", spec_lookup=registry.get, nonce=proposal.arm_nonce)


async def test_one_thread_junked_is_proven_and_its_undo_puts_it_back(engine, session, box):
    session.issue("18f00000000000a1")
    text, proposal = await stage_one(session, "gmail_thread_junk", thread_id="18f00000000000a1")
    assert text.startswith("PROPOSED") and proposal.interaction == "hold_to_arm"
    card = present_state(proposal, session)
    assert card["title"] == "Junk the thread"
    assert {"label": "From", "value": "Promo Bot <deals@example.net>"}.items() <= next(f for f in card["facts"] if f["label"] == "From").items()
    tap = await engine.commit(proposal.proposal_id, proposal.session_id, caller="o", spec_lookup=registry.get)
    assert tap.code == "not_armed" and "SPAM" not in box.thread_labels("18f00000000000a1"), "a tap without the hold junks nothing"
    result = await hold_one(engine, proposal)
    assert result.code == "verified" and result.spoken == "Junked."
    assert proposal.after == {"inbox": False, "spam": True}
    ui = present_state(proposal, session, full=True)
    assert any(item["data"].get("archived") == {"kind": "email_thread", "ref": "18f00000000000a1"} for item in ui if item["type"] == "success"), \
        "the tablet takes the thread off its deck as it does for an archive"
    undo = session.proposal(proposal.undo_id)
    back = await hold_one(engine, undo)
    assert back.code == "verified" and "INBOX" in box.thread_labels("18f00000000000a1") and "SPAM" not in box.thread_labels("18f00000000000a1")


async def test_one_thread_from_a_customer_or_our_own_is_refused(engine, session, box):
    session.issue("18f00000000000a3", "18f00000000000a4")
    text, proposal = await stage_one(session, "gmail_thread_junk", thread_id="18f00000000000a3")
    assert proposal is None and "from a customer of the shop" in text
    text, proposal = await stage_one(session, "gmail_thread_junk", thread_id="18f00000000000a4")
    assert proposal is None and "already in Spam" in text


# ------------------------------------------------------------------- every sender, every Reply-To
#
# The review of 8 October (note 1): the check looked only at the latest inbound message's From, so a
# Shopify contact-form thread (From mailer@shopify.com, Reply-To the customer) and a thread a customer
# began and someone else wrote last were both staged. Every sender and every Reply-To is checked now.

CONTACT_FORM = "18f00000000000b1"
CUSTOMER_FIRST = "18f00000000000b2"


def contact_form(box):
    box.threads[CONTACT_FORM] = [msg("b1", from_="Shopify <mailer@shopify.com>", subject="New customer message on 8 Oct", mid="<b1@x>",
                                     labels=["INBOX", "UNREAD"], reply_to="Ana Fixture <ana@example.com>")]


def customer_first(box):
    box.threads[CUSTOMER_FIRST] = [
        msg("b2", from_="Ana Fixture <ana@example.com>", subject="Where is my order?", mid="<b2@x>", labels=["INBOX"]),
        msg("b3", from_="Promo Bot <deals@example.net>", subject="Re: Where is my order?", mid="<b3@x>", labels=["INBOX"]),
    ]


async def test_a_contact_form_thread_whose_reply_to_is_a_customer_is_never_junked(engine, batches, session, box):
    contact_form(box)
    session.issue(CONTACT_FORM)
    text, proposal = await stage_one(session, "gmail_thread_junk", thread_id=CONTACT_FORM)
    assert proposal is None and "from a customer of the shop" in text, text
    ws = sets.create(session, kind="emails", members=[CONTACT_FORM, "18f00000000000a1"], label="email: today",
                     labels={CONTACT_FORM: "New customer message on 8 Oct", "18f00000000000a1": "WIN A PRIZE"})
    _, batch, _ = await stage(session, "batch_email_junk", set_id=ws.set_id)
    assert [c.label for c in batch.eligible] == ["WIN A PRIZE"]
    assert {c.label: c.excluded for c in batch.excluded}["New customer message on 8 Oct"].startswith("from a customer of the shop")
    await gesture(batches, batch)
    assert "INBOX" in box.thread_labels(CONTACT_FORM) and "SPAM" not in box.thread_labels(CONTACT_FORM), "the customer's message stays"
    assert not [c for c in box.calls if c[0] == "modify" and c[1] == CONTACT_FORM]


async def test_a_thread_a_customer_began_is_never_junked_whoever_wrote_last(engine, batches, session, box):
    customer_first(box)
    session.issue(CUSTOMER_FIRST)
    text, proposal = await stage_one(session, "gmail_thread_junk", thread_id=CUSTOMER_FIRST)
    assert proposal is None and "from a customer of the shop" in text, text
    ws = sets.create(session, kind="emails", members=[CUSTOMER_FIRST, "18f00000000000a1"], label="email: today",
                     labels={CUSTOMER_FIRST: "Re: Where is my order?", "18f00000000000a1": "WIN A PRIZE"})
    _, batch, _ = await stage(session, "batch_email_junk", set_id=ws.set_id)
    assert [c.label for c in batch.eligible] == ["WIN A PRIZE"]
    assert "Re: Where is my order?" in {c.label for c in batch.excluded}
    assert "INBOX" in box.thread_labels(CUSTOMER_FIRST)


async def test_a_reply_to_the_shop_could_not_be_asked_about_is_not_junked(engine, session, box, monkeypatch):
    async def ana_unknown(email: str) -> bool:
        if email == "ana@example.com":
            raise RuntimeError("Shopify is down")
        return False

    monkeypatch.setattr(gmail_tools, "_customer_lookup", ana_unknown)
    contact_form(box)
    session.issue(CONTACT_FORM)
    text, proposal = await stage_one(session, "gmail_thread_junk", thread_id=CONTACT_FORM)
    assert proposal is None and "could not be checked against the shop's customers" in text, "unknown is RED, in Reply-To too"


async def test_the_junk_keeps_the_subject_off_the_ledger(engine, session, box, tmp_path):
    from app.actions.ledger import ActionLedger
    engine.ledger = ActionLedger(tmp_path)
    session.issue("18f00000000000a1")
    await stage_one(session, "gmail_thread_junk", thread_id="18f00000000000a1")
    written = (tmp_path / "actions.jsonl").read_text(encoding="utf-8")
    assert "WIN A PRIZE" not in written and "deals@example.net" not in written and '"kind": "junk"' in written


def present_state(proposal, session, *, full: bool = False):
    from app.presentation import present_proposal_state

    ui = present_proposal_state(proposal, session=session)
    return ui if full else ui[0]["data"]
