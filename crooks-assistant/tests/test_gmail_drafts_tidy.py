"""Ruling 28 (DEC-071): CLIVE takes away the Gmail drafts it made and never sent — and only those.

Provenance is CLIVE's own record, written when Gmail answers CLIVE's own create; a draft is CLIVE's
to delete only while Gmail still holds it unsent, with the message id Gmail gave CLIVE, CLIVE's own
Message-ID and the words CLIVE wrote. When: a reply sent in the same thread replaces it (the card
says so before the hold, and it goes inside that change once the send is proven), or it went unused
for fourteen days (CLIVE looks every few hours). Every deletion is proven by reading back. The inbox
is a fake in memory; nothing reaches a network."""

from __future__ import annotations

import asyncio
import json
import os
import time

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import ActionLedger, NullLedger
from app.clients.gmail import GmailClient, GmailNotFound, GmailRefused
from app.presentation import present_proposal_state
from app.session.models import Session
from app.tools import authority, gmail_drafts, gmail_writes
from tests.test_gmail_writes import (
    BODY,
    CUSTOMER_ID,
    ORDER,
    THREAD,
    FakeGmail,
    Policy,
    customer_of,
    hold,
    stage,
    tap,
)
from tests.test_screen_paths import MINE, world  # noqa: F401 (the fixture)

pytestmark = pytest.mark.usefixtures("owner_asking")


class Inbox(FakeGmail):
    """The fake inbox, answering a missing draft as Gmail does: a 404 (GmailNotFound), not a failure.
    `forbid` makes every draft read a 403 from then on, as a Gmail that refuses without saying."""

    forbid = False

    def get_draft(self, draft_id: str) -> dict:
        if self.forbid:
            raise GmailRefused("Could not read the draft: forbidden")
        if draft_id not in self.drafts:
            raise GmailNotFound("Could not read the draft: not found")
        return super().get_draft(draft_id)

    def edit_in_gmail(self, draft_id: str, body: str) -> None:
        """George opens the draft in Gmail and changes it: Gmail gives it a new message id."""
        d = self.drafts[draft_id]
        old = d["message_id"]
        d["message_id"] = self._next("e")
        d["parsed"] = dict(d["parsed"], body=body)
        for m in self.threads.get(d["thread_id"], []):
            if m["id"] == old:
                m["id"] = d["message_id"]
                m["body"] = body


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    monkeypatch.setattr(gmail_writes, "SETTLE_POLL_S", 0.0)
    monkeypatch.setattr(gmail_writes, "SETTLE_S", 0.5)
    return e


@pytest.fixture()
def session():
    s = Session(session_id="c1")       # the session the helpers of tests/test_gmail_writes.py commit in
    s.issue(ORDER, THREAD, CUSTOMER_ID)
    s.epoch = 1
    return s


@pytest.fixture()
def box(tmp_path):
    inbox = Inbox()
    gmail_writes.bind(inbox, customer=customer_of, policy=lambda: Policy())
    gmail_drafts.configure(tmp_path / "gmail-drafts.json")
    yield inbox
    gmail_writes.bind(None)
    gmail_drafts.configure(None)


async def saved_draft(box, engine, session, body: str = BODY):
    _, proposal = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=body)
    result = await tap(engine, proposal)
    assert result.code == "verified"
    (draft_id,) = [d for d in box.drafts if box.drafts[d]["parsed"]["body"].startswith(body.split("\n")[0])]
    return draft_id, proposal


# ------------------------------------------------------------------------------- provenance


async def test_a_draft_clive_saves_is_written_down_as_clives_and_nothing_personal_is_kept(box, engine, session, tmp_path):
    draft_id, proposal = await saved_draft(box, engine, session)
    found = gmail_drafts.row(draft_id)
    assert found["state"] == "waiting" and found["by"] == "owner" and found["kind"] == "reply" and found["thread_id"] == THREAD
    assert found["token"] == proposal.execution["token"] and found["message_id"] == box.drafts[draft_id]["message_id"]
    assert found["words"] == gmail_drafts.fingerprint(box.drafts[draft_id]["parsed"]["body"]), "the words' fingerprint, from Gmail's own copy"
    written = (tmp_path / "gmail-drafts.json").read_text(encoding="utf-8")
    assert "daniel" not in written.lower() and "Order 1930" not in written and "packed today" not in written, "no address, subject or words"
    assert oct(os.stat(tmp_path / "gmail-drafts.json").st_mode & 0o777) == "0o600"


async def test_the_undo_of_a_saved_draft_settles_it_in_the_record(box, engine, session):
    draft_id, proposal = await saved_draft(box, engine, session)
    undo = session.proposal(proposal.undo_id)
    assert (await tap(engine, undo)).code == "verified"
    assert draft_id not in box.drafts and gmail_drafts.row(draft_id)["state"] == "deleted"


def test_a_draft_written_in_gmail_is_nobodys_but_georges():
    assert gmail_drafts.words_of(draft_id="draft-not-ours") == "", "not in CLIVE's record: never CLIVE's"


# ------------------------------------------------------------------- a send replaced it


async def test_a_reply_sent_in_the_thread_takes_away_clives_earlier_draft_and_says_so_first(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)
    text, send = await stage(session, "gmail_send_reply", thread_id=THREAD, body="Hi Daniel, it went out this morning.")
    assert text.startswith("PROPOSED") and send.execution["replaces"] == [draft_id]
    card = present_proposal_state(send, session=session)[0]["data"]
    earlier = [f for f in card["facts"] if f["label"] == "Earlier draft"]
    assert earlier and earlier[0]["value"].startswith("CLIVE's unsent draft here from ") and earlier[0]["value"].endswith("is deleted once this goes")
    assert draft_id in box.drafts, "nothing is taken away before the hold"
    result = await hold(engine, send)
    assert result.code == "verified" and result.spoken == "Reply sent to Daniel."
    assert draft_id not in box.drafts and ("delete_draft", draft_id) in box.calls
    assert gmail_drafts.row(draft_id)["state"] == "deleted" and gmail_drafts.row(draft_id)["why"] == "a send replaced it"


async def test_a_send_that_is_refused_takes_nothing_away(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)
    _, send = await stage(session, "gmail_send_reply", thread_id=THREAD, body="Hi Daniel, it went out this morning.")
    box.fail_send = True
    result = await hold(engine, send)
    assert result.code != "verified" and draft_id in box.drafts and gmail_drafts.row(draft_id)["state"] == "waiting"


async def test_a_draft_george_edited_in_gmail_is_his_now_and_is_never_taken(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)
    box.edit_in_gmail(draft_id, "Hi Daniel, George here — I've added a note for you.")
    text, send = await stage(session, "gmail_send_reply", thread_id=THREAD, body="Hi Daniel, it went out this morning.")
    assert send.execution["replaces"] == [] and "Earlier draft" not in json.dumps(present_proposal_state(send, session=session))
    assert gmail_drafts.row(draft_id)["state"] == "kept" and gmail_drafts.row(draft_id)["why"] == "edited since CLIVE made it"
    await hold(engine, send)
    assert draft_id in box.drafts, "his words stay"
    assert (await gmail_drafts.sweep(time.time() + 30 * 86400))["deleted"] == 0 and draft_id in box.drafts


async def test_a_draft_edited_between_the_card_and_the_hold_is_kept_and_the_card_after_says_so(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)
    _, send = await stage(session, "gmail_send_reply", thread_id=THREAD, body="Hi Daniel, it went out this morning.")
    box.edit_in_gmail(draft_id, "Hi Daniel, a different thought.")
    result = await hold(engine, send)
    assert result.code == "verified" and "CLIVE's earlier draft was changed meanwhile, so it was kept." in result.spoken
    assert draft_id in box.drafts


# ----------------------------------------------------------------------------- by age


async def test_the_sweep_takes_away_only_clives_untouched_drafts_older_than_two_weeks(box, engine, session):
    old_id, _ = await saved_draft(box, engine, session, body="An old reply nobody sent.")
    young_id, _ = await saved_draft(box, engine, session, body="A reply saved just now.")
    gmails_own = box.create_draft(gmail_writes.build_raw(sender="team@crooksldn.com", sender_name="CROOKS", to="daniel@example.com", to_name="", subject="Note",
                                                         body="George wrote this one in Gmail.", token="<georges@crooksldn.com>"), None)["draft_id"]
    with gmail_drafts._lock:
        data = gmail_drafts._load()
        data["drafts"][old_id]["made_at"] = time.time() - 15 * 86400
        gmail_drafts._save(data)
    counts = await gmail_drafts.sweep()
    assert counts["deleted"] == 1 and old_id not in box.drafts
    assert gmail_drafts.row(old_id)["state"] == "deleted" and gmail_drafts.row(old_id)["why"] == "unused for 14 days"
    assert young_id in box.drafts and gmail_drafts.row(young_id)["state"] == "waiting", "two weeks, not sooner"
    assert gmails_own in box.drafts, "a draft CLIVE did not make is never touched"


# ------------------------------------------- recorded, told once, never a draft a card names
#
# The review of 8 October (note 3) and ruling 28 (DEC-071, "delete the unused drafts": Y): the
# fourteen-day clock stays, but each draft it deletes is written in the action ledger (ids and a
# count — no words, no recipient, no subject), George is told once, plainly, "CLIVE cleared N of its
# unused drafts" at the end of his next answer, and a draft a card waiting for its hold names is never
# taken by the clock.


def aged(*draft_ids: str, days: float = 15) -> None:
    with gmail_drafts._lock:
        data = gmail_drafts._load()
        for draft_id in draft_ids:
            data["drafts"][draft_id]["made_at"] = time.time() - days * 86400
        gmail_drafts._save(data)


def ledger_lines(tmp_path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


async def test_each_draft_the_clock_deletes_is_in_the_action_ledger_by_id_and_count_only(box, engine, session, tmp_path):
    engine.ledger = ActionLedger(tmp_path / "logs")
    one, _ = await saved_draft(box, engine, session, body="An old reply nobody sent.")
    two, _ = await saved_draft(box, engine, session, body="Another old reply.")
    aged(one, two)
    assert (await gmail_drafts.sweep())["deleted"] == 2
    cleared = [e for e in ledger_lines(tmp_path) if e["event"] == "DRAFTS_CLEARED"]
    assert len(cleared) == 1, cleared
    entry = cleared[0]
    assert set(entry) == {"ts", "iso", "event", "operation", "caller", "count", "ids", "reason"}, entry
    assert entry["operation"] == "gmail_drafts_tidy" and entry["caller"] == "clive" and entry["reason"] == "unused for 14 days"
    assert entry["count"] == 2 and sorted(entry["ids"]) == sorted([one, two])
    written = json.dumps(entry).lower()
    assert "daniel" not in written and "order 1930" not in written and "nobody sent" not in written, "no words, no recipient, no subject"


async def test_a_draft_a_send_replaced_is_in_the_action_ledger_too(box, engine, session, tmp_path):
    engine.ledger = ActionLedger(tmp_path / "logs")
    draft_id, _ = await saved_draft(box, engine, session)
    _, send = await stage(session, "gmail_send_reply", thread_id=THREAD, body="Hi Daniel, it went out this morning.")
    assert (await hold(engine, send)).code == "verified" and draft_id not in box.drafts
    (entry,) = [e for e in ledger_lines(tmp_path) if e["event"] == "DRAFTS_CLEARED"]
    assert entry["ids"] == [draft_id] and entry["count"] == 1 and entry["reason"] == "a send replaced it"


async def test_george_is_told_once_how_many_the_clock_cleared_and_a_team_member_never_is(box, engine, session):
    from app.routes import turn as turn_route

    one, _ = await saved_draft(box, engine, session, body="An old reply nobody sent.")
    two, _ = await saved_draft(box, engine, session, body="Another old reply.")
    aged(one, two)
    await gmail_drafts.sweep()
    with authority.acting_as(authority.for_staff("mia-fixture", "mia@example.com")):
        assert turn_route._with_drafts_cleared("Here it is.") == "Here it is.", "a team member's answer never takes it"
    assert turn_route._with_drafts_cleared("Here it is.") == "Here it is. CLIVE cleared 2 of its unused drafts."
    assert turn_route._with_drafts_cleared("And the next one.") == "And the next one.", "once"
    assert gmail_drafts.take_cleared_line() == ""


async def test_the_owners_next_answer_ends_with_it_once(world, tmp_path, monkeypatch):  # noqa: F811 - the fixture
    """Where he sees it: the end of his next answer, on the screen and in the voice, through the real
    turn — once."""
    monkeypatch.setattr(gmail_drafts, "_path", tmp_path / "told" / "gmail-drafts.json")
    gmail_drafts._save({"version": 1, "drafts": {}, "untold": 3})
    world.model.script = []
    first = (await world.client.post("/turn", json={"text": "anything new?", "session_id": "t1"}, headers=MINE)).json()
    assert first["answer"].endswith(" CLIVE cleared 3 of its unused drafts."), first["answer"]
    second = (await world.client.post("/turn", json={"text": "and now?", "session_id": "t1"}, headers=MINE)).json()
    assert "cleared" not in second["answer"], second["answer"]


async def test_a_reply_that_replaced_a_draft_is_not_counted_for_the_telling(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)
    _, send = await stage(session, "gmail_send_reply", thread_id=THREAD, body="Hi Daniel, it went out this morning.")
    assert (await hold(engine, send)).code == "verified" and draft_id not in box.drafts
    assert gmail_drafts.take_cleared_line() == "", "the card said so before the hold"


async def test_a_draft_a_card_waiting_for_its_hold_sends_is_never_taken_by_the_clock(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)
    aged(draft_id)
    session.epoch += 1
    _, send = await stage(session, "gmail_send_reply", thread_id=THREAD)
    assert send is not None and send.execution["draft_id"] == draft_id, "the card sends the waiting draft"
    counts = await gmail_drafts.sweep()
    assert counts["deleted"] == 0 and counts["on_a_card"] == 1, counts
    assert draft_id in box.drafts and gmail_drafts.row(draft_id)["state"] == "waiting"
    assert not [c for c in box.calls if c[0] == "delete_draft"]
    result = await hold(engine, send)
    assert result.code == "verified", "the hold still sends what the card showed"


async def test_a_draft_a_waiting_card_says_it_replaces_is_never_taken_by_the_clock(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)
    aged(draft_id)
    _, send = await stage(session, "gmail_send_reply", thread_id=THREAD, body="Hi Daniel, it went out this morning.")
    assert send.execution["replaces"] == [draft_id]
    counts = await gmail_drafts.sweep()
    assert counts["deleted"] == 0 and counts["on_a_card"] == 1 and draft_id in box.drafts, counts
    assert (await hold(engine, send)).code == "verified" and draft_id not in box.drafts, "the hold takes it, as its card said"
    assert gmail_drafts.take_cleared_line() == ""


async def test_with_no_way_to_tell_which_drafts_a_card_names_the_clock_takes_nothing(box, engine, session, monkeypatch):
    draft_id, _ = await saved_draft(box, engine, session)
    aged(draft_id)

    def broken():
        raise RuntimeError("the engine could not be read")

    monkeypatch.setattr(engine, "open_proposals", broken)
    assert (await gmail_drafts.sweep())["deleted"] == 0 and draft_id in box.drafts


async def test_a_draft_that_was_sent_is_settled_as_sent_and_nothing_is_deleted(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)
    box.send_draft(draft_id)
    counts = await gmail_drafts.sweep(time.time() + 15 * 86400)
    assert counts["sent"] == 1 and gmail_drafts.row(draft_id)["state"] == "sent"
    assert not [c for c in box.calls if c[0] == "delete_draft"]


async def test_a_delete_that_cannot_be_proven_stays_waiting_and_is_tried_again(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)
    box.delete_draft = lambda d: box.calls.append(("delete_draft", d))   # Gmail answers, and keeps it
    counts = await gmail_drafts.sweep(time.time() + 15 * 86400)
    assert counts["waiting"] == 1 and draft_id in box.drafts and gmail_drafts.row(draft_id)["state"] == "waiting"


# ------------------------------------------------------------- only a 404 proves it gone
#
# The review of 8 October (note 5): any 4xx on the read-back was taken as "deleted". A 403 on both the
# delete and the read-back was recorded DELETED, with a draft_tidied event, while the draft stayed in
# Gmail. Only Gmail's 404 proves a draft gone; any other refusal is "couldn't confirm".


def test_the_client_tells_a_404_from_any_other_refusal():
    class Answered(Exception):
        def __init__(self, status: int) -> None:
            super().__init__(f"HTTP {status}")
            self.status_code = status

    client = GmailClient()
    for status, kind in ((404, GmailNotFound), (403, GmailRefused), (400, GmailRefused)):
        def fail(status=status):
            raise Answered(status)
        with pytest.raises(GmailRefused) as raised:
            client._run("Could not read the draft", fail)
        assert type(raised.value) is kind, status


async def test_a_403_on_the_delete_and_its_read_back_is_not_a_deletion(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)

    def refused(d):
        box.calls.append(("delete_draft", d))
        box.forbid = True
        raise GmailRefused("Could not delete the draft: forbidden")

    box.delete_draft = refused
    counts = await gmail_drafts.sweep(time.time() + 15 * 86400)
    assert counts["deleted"] == 0 and counts["unconfirmed"] == 1, counts
    assert draft_id in box.drafts and gmail_drafts.row(draft_id)["state"] == "waiting", "not proven gone: still CLIVE's to look at again"


async def test_a_send_whose_replaced_draft_cannot_be_confirmed_gone_says_so(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)
    _, send = await stage(session, "gmail_send_reply", thread_id=THREAD, body="Hi Daniel, it went out this morning.")
    assert send.execution["replaces"] == [draft_id]

    def refused(d):
        box.calls.append(("delete_draft", d))
        box.forbid = True
        raise GmailRefused("Could not delete the draft: forbidden")

    box.delete_draft = refused
    result = await hold(engine, send)
    assert result.code == "verified" and "CLIVE couldn't confirm its earlier draft was deleted" in result.spoken, result.spoken
    assert draft_id in box.drafts and gmail_drafts.row(draft_id)["state"] == "waiting"


async def test_a_403_when_checking_a_draft_is_not_taken_for_gone(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)
    box.forbid = True
    counts = await gmail_drafts.sweep(time.time() + 15 * 86400)
    assert counts["gone"] == 0 and counts["sent"] == 0 and gmail_drafts.row(draft_id)["state"] == "waiting", counts
    assert not [c for c in box.calls if c[0] == "delete_draft"]


# ------------------------------------------------------------- a hung Gmail read is bounded
#
# The review of 8 October (note 7): after a send, and after a draft was saved, CLIVE read the draft's
# words from Gmail with no time limit, so a hung read held the commit after the email had gone. Every
# read here runs inside `_call`, with its limit.


async def hung(draft_id):
    await asyncio.sleep(30)


async def test_a_hung_read_after_a_send_never_holds_the_commit(box, engine, session, monkeypatch):
    draft_id, _ = await saved_draft(box, engine, session)
    _, send = await stage(session, "gmail_send_reply", thread_id=THREAD, body="Hi Daniel, it went out this morning.")
    assert send.execution["replaces"] == [draft_id]
    monkeypatch.setattr(gmail_writes, "_draft_text", hung)
    monkeypatch.setattr(gmail_drafts, "CALL_TIMEOUT_S", 0.2)
    result = await asyncio.wait_for(hold(engine, send), timeout=5)
    assert result.code == "verified" and "could not be deleted just now" in result.spoken, result.spoken
    assert draft_id in box.drafts and gmail_drafts.row(draft_id)["state"] == "waiting"


async def test_a_hung_read_after_a_draft_is_saved_never_holds_the_commit(box, engine, session, monkeypatch):
    monkeypatch.setattr(gmail_writes, "_draft_text", hung)
    monkeypatch.setattr(gmail_drafts, "CALL_TIMEOUT_S", 0.2)
    _, proposal = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    result = await asyncio.wait_for(tap(engine, proposal), timeout=5)
    assert result.code == "verified"
    (draft_id,) = list(box.drafts)
    found = gmail_drafts.row(draft_id)
    assert found["state"] == "waiting" and found["words"] == "", "its words could not be read back: written down, never tidied"


async def test_a_record_without_the_words_fingerprint_is_never_tidied(box, engine, session):
    draft_id, _ = await saved_draft(box, engine, session)
    with gmail_drafts._lock:
        data = gmail_drafts._load()
        data["drafts"][draft_id]["words"] = ""
        gmail_drafts._save(data)
    assert (await gmail_drafts.sweep(time.time() + 15 * 86400))["kept"] == 1 and draft_id in box.drafts


async def test_a_latched_read_only_backend_deletes_nothing(box, engine, session, monkeypatch):
    from app import readonly

    draft_id, _ = await saved_draft(box, engine, session)
    monkeypatch.setattr(readonly, "active", lambda: True)
    await gmail_drafts.sweep(time.time() + 15 * 86400)
    assert draft_id in box.drafts and gmail_drafts.row(draft_id)["state"] == "waiting"


async def test_the_clock_looks_only_while_changes_are_switched_on(monkeypatch):
    seen = []

    async def counted(now=None):
        seen.append(now)
        return {}

    monkeypatch.setattr(gmail_drafts, "sweep", counted)
    monkeypatch.setattr(gmail_drafts, "FIRST_SWEEP_S", 0.0)
    monkeypatch.setattr(gmail_drafts, "SWEEP_EVERY_S", 0.01)
    switched = {"on": False}
    gmail_drafts.start(lambda: switched["on"])
    await asyncio.sleep(0.05)
    assert seen == [], "changes off: CLIVE never looks"
    switched["on"] = True
    await asyncio.sleep(0.05)
    await gmail_drafts.stop()
    assert seen, "changes on: it looks"
