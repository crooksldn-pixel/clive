"""Ruling 34 (DEC-071): a member of the team may send a draft George left, on their own hold.

gmail_unsent lists the drafts waiting in Gmail and says whose words each is; gmail_send_draft sends
the one draft in a thread exactly as Gmail holds it — nothing written or changed — and its card says
whose words they are and who sends them. It is the team's one email write beyond answering a thread
themselves, and it reaches only George's drafts (written in Gmail, or drafted with CLIVE on his
hold) or the asker's own. The engine records who held it; the work list records it as theirs. The
inbox is a fake in memory; nothing reaches a network."""

from __future__ import annotations

import json

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import ActionLedger, NullLedger
from app.people import staff
from app.people.store import people
from app.presentation import present_proposal_state
from app.tools import authority, gmail_drafts, gmail_writes, registry
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from app.work import hooks
from app.work.store import work
from tests.test_gmail_drafts_tidy import Inbox
from tests.test_gmail_writes import THREAD, Policy, customer_of

MIA = "mia@example.com"
ME = "team@crooksldn.com"


class Drafts(Inbox):
    """The fake inbox, listing every draft for "in:draft" as Gmail does."""

    def list_drafts(self, query: str) -> list[dict]:
        if query == "in:draft":
            self.calls.append(("drafts", query))
            return [{"draft_id": k, "message_id": d["message_id"], "thread_id": d["thread_id"]} for k, d in self.drafts.items()]
        return super().list_drafts(query)


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    monkeypatch.setattr(gmail_writes, "SETTLE_POLL_S", 0.0)
    monkeypatch.setattr(gmail_writes, "SETTLE_S", 0.5)
    return e


@pytest.fixture()
def box(tmp_path):
    inbox = Drafts()
    gmail_writes.bind(inbox, customer=customer_of, policy=lambda: Policy())
    gmail_drafts.configure(tmp_path / "gmail-drafts.json")
    people.configure(tmp_path / "people.json")
    work.configure(tmp_path / "work")
    people.note({"name": "Mia Fixture", "kind": "staff"})
    people.note({"name": "Kai Fixture", "kind": "staff"})
    yield inbox
    gmail_writes.bind(None)
    gmail_drafts.configure(None)
    people.configure(None)
    work.configure(None)


def georges_draft(box, *, body="Hi Daniel, George here. Yours ships Monday — sorry for the wait.") -> str:
    """A reply George wrote in Gmail: a draft in the customer's thread that CLIVE did not make."""
    raw = gmail_writes.build_raw(sender=ME, sender_name="CROOKS", to="daniel@example.com", to_name="Daniel Stub", subject="Re: Order 1930 — where is it?",
                                 body=body, token="<george-gmail-1@crooksldn.com>", in_reply_to="<abc@example.com>", references="<abc@example.com>")
    return box.create_draft(raw, THREAD)["draft_id"]


def as_owner():
    return authority.acting_as(authority.for_owner("owner@example.com"))


def as_staff(person_id: str, login: str = MIA):
    return authority.acting_as(authority.for_staff(person_id, login))


class Talk:
    """One conversation, whose tool calls are made the way the turn makes them (`call`)."""

    def __init__(self, session_id: str) -> None:
        from app.session.models import Session

        self.session = Session(session_id=session_id)
        self.session.epoch = 1


async def call(talk: Talk, tool: str, **args):
    """A tool called through the dispatcher and the gate, as the turn calls it."""
    before = len(talk.session.proposals)
    text = await dispatch(tool, args, session=talk.session, timeout_s=5)
    return text, (talk.session.proposals[-1] if len(talk.session.proposals) > before else None)


async def held(engine, proposal, caller: str):
    armed, code = engine.arm(proposal.proposal_id, proposal.session_id)
    assert code == "", code
    proposal.armed_at -= 1.0
    return await engine.commit(proposal.proposal_id, proposal.session_id, caller=caller, spec_lookup=registry.get, nonce=proposal.arm_nonce)


def facts_of(proposal, session) -> dict[str, str]:
    card = present_proposal_state(proposal, session=session)[0]["data"]
    return {f["label"]: f["value"] for f in card["facts"]}


# ------------------------------------------------------------------------- declaration


def test_the_send_is_a_held_irreversible_email_write_and_the_list_is_a_read():
    spec = registry.get("gmail_send_draft")
    assert spec.tier is Tier.RED and spec.write.complete and spec.write.kind == "irreversible" and spec.write.mutation == "gmail:send"
    assert spec.input_schema["required"] == ["thread_id"] and set(spec.input_schema["properties"]) == {"thread_id"}, "no words, no recipient: Gmail's"
    assert classify("gmail_send_draft", {"thread_id": THREAD}, issued_ids={THREAD}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify("gmail_send_draft", {"thread_id": THREAD}).disposition is Disposition.DENY, "an unissued thread"
    unsent = registry.get("gmail_unsent")
    assert unsent.tier is Tier.AMBER and unsent.write is None and unsent.batch is None
    assert classify("gmail_unsent", {}).disposition is Disposition.EXECUTE_NOW


def test_the_team_may_list_the_drafts_and_send_one_and_nothing_more_was_given():
    assert "gmail_unsent" in staff.READS and "gmail_send_draft" in staff.WRITES and staff.may_commit("gmail_send_draft")
    assert "gmail_send_new" not in staff.TOOLS and "gmail_draft_new" not in staff.TOOLS, "still no new email to anyone"
    assert hooks.EFFECTS["gmail_send_draft"] == ("draft_sent", "email", True)


# ------------------------------------------------------------------------- the owner


async def test_george_sends_his_own_gmail_draft_as_it_is_and_the_card_says_so(engine, box):
    draft_id = georges_draft(box)
    talk = Talk("o1")
    with as_owner():
        listed = await call(talk, "gmail_unsent")
        assert '"words": "Yours, written in Gmail"' in listed[0] and THREAD in listed[0]
        text, proposal = await call(talk, "gmail_send_draft", thread_id=THREAD)
    assert text.startswith("PROPOSED") and proposal.interaction == "hold_to_arm"
    facts = facts_of(proposal, talk.session)
    assert facts["Words"] == "Yours, written in Gmail" and facts["Sent by"] == "You, on your hold"
    assert facts["To"] == "Daniel Stub <daniel@example.com>" and facts["Draft"] == "the one waiting in Gmail, as it reads now"
    card = present_proposal_state(proposal, session=talk.session)[0]["data"]
    assert card["message"]["editable"] == [] and card["message"]["other"] is None and card["message"]["kind"] == "reply", "his words are not changed here"
    with as_owner():
        result = await held(engine, proposal, "owner@example.com")
    assert result.code == "verified" and result.spoken == "Sent to Daniel."
    assert ("send_draft", draft_id) in box.calls and not [c for c in box.calls if c[0] == "send"], "the draft itself went, not new words"


# ------------------------------------------------------------------------- the team


async def test_mia_sends_georges_draft_on_her_own_hold_and_it_is_recorded_as_hers(engine, box, tmp_path):
    engine.ledger = ActionLedger(tmp_path / "logs")
    draft_id = georges_draft(box)
    talk = Talk("m1")
    with as_staff("mia-fixture"):
        listed = (await call(talk, "gmail_unsent"))[0]
        assert "George's, written in Gmail" in listed
        text, proposal = await call(talk, "gmail_send_draft", thread_id=THREAD)
        assert text.startswith("PROPOSED")
        facts = facts_of(proposal, talk.session)
        assert facts["Words"] == "George's, written in Gmail" and facts["Sent by"] == "Mia, on their own hold"
        result = await held(engine, proposal, MIA)
        hooks.after_commit(proposal)
    assert result.code == "verified" and ("send_draft", draft_id) in box.calls
    lines = [json.loads(line) for line in (tmp_path / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    executed = [e for e in lines if e["event"] == "EXECUTING" and e["operation"] == "gmail_send_draft"]
    assert executed and executed[0]["caller"] == MIA, "the ledger names whose hold sent it"
    proposed = [e for e in lines if e["event"] == "PROPOSED" and e["operation"] == "gmail_send_draft"][0]
    assert proposed["facts"]["words"] == "gmail" and proposed["facts"]["sender"] == "staff"
    assert "daniel" not in json.dumps(lines).lower() and "Monday" not in json.dumps(lines), "nobody's details in the ledger"
    record = work.history()[0]
    assert (record["who"], record["what"]) == ("mia-fixture", "draft_sent")


async def test_a_draft_george_made_with_clive_is_his_on_mias_card(engine, box):
    with as_owner():
        talk = Talk("o2")
        talk.session.issue(THREAD)
        _, saved = await call(talk, "gmail_draft_reply", thread_id=THREAD, body="Hi Daniel, it ships Monday.")
        assert (await engine.commit(saved.proposal_id, "o2", caller="owner@example.com", spec_lookup=registry.get)).code == "verified"
    mia = Talk("m2")
    mia.session.issue(THREAD)
    with as_staff("mia-fixture"):
        _, proposal = await call(mia, "gmail_send_draft", thread_id=THREAD)
    assert facts_of(proposal, mia.session)["Words"] == "George's, drafted with CLIVE"


async def test_another_team_members_draft_is_theirs_or_georges_to_send(engine, box):
    kai = Talk("k1")
    kai.session.issue(THREAD)
    with as_staff("kai-fixture", "kai@example.com"):
        _, saved = await call(kai, "gmail_draft_reply", thread_id=THREAD, body="Hi Daniel, Kai here. Monday.")
        assert (await engine.commit(saved.proposal_id, "k1", caller="kai@example.com", spec_lookup=registry.get)).code == "verified"
    mia = Talk("m3")
    mia.session.issue(THREAD)
    with as_staff("mia-fixture"):
        text, proposal = await call(mia, "gmail_send_draft", thread_id=THREAD)
    assert proposal is None and "That draft is Kai's words" in text
    with as_staff("kai-fixture", "kai@example.com"):
        _, own = await call(kai, "gmail_send_draft", thread_id=THREAD)
    assert facts_of(own, kai.session)["Words"] == "Yours, drafted with CLIVE"


async def test_a_draft_changed_after_the_card_is_not_sent(engine, box):
    draft_id = georges_draft(box)
    talk = Talk("m4")
    talk.session.issue(THREAD)
    with as_staff("mia-fixture"):
        _, proposal = await call(talk, "gmail_send_draft", thread_id=THREAD)
        box.drafts[draft_id]["parsed"]["body"] = "George changed his mind."
        result = await held(engine, proposal, MIA)
    assert result.code == "stale" and not [c for c in box.calls if c[0] == "send_draft"]


async def test_two_drafts_in_a_thread_are_never_guessed_between(engine, box):
    georges_draft(box)
    georges_draft(box, body="A second go.")
    talk = Talk("m5")
    talk.session.issue(THREAD)
    with as_staff("mia-fixture"):
        text, proposal = await call(talk, "gmail_send_draft", thread_id=THREAD)
    assert proposal is None and "There are 2 drafts waiting" in text


async def test_the_draft_sent_by_answering_its_thread_says_the_same_and_keeps_the_same_rule(engine, box):
    """gmail_send_reply with no words sends the one draft waiting in the thread: the team could, and
    can, send George's that way too — and that card says whose words and who sends, as this one does,
    and refuses another member's draft the same way."""
    georges_draft(box)
    mia = Talk("m6")
    mia.session.issue(THREAD)
    with as_staff("mia-fixture"):
        _, proposal = await call(mia, "gmail_send_reply", thread_id=THREAD)
    said = facts_of(proposal, mia.session)
    assert said["Words"] == "George's, written in Gmail" and said["Sent by"] == "Mia, on their own hold"
    kai_thread = Talk("k2")
    kai_thread.session.issue(THREAD)
    box.drafts.clear()
    box.threads[THREAD] = [m for m in box.threads[THREAD] if "DRAFT" not in m["labels"]]
    with as_staff("kai-fixture", "kai@example.com"):
        _, saved = await call(kai_thread, "gmail_draft_reply", thread_id=THREAD, body="Hi Daniel, Kai here.")
        assert (await engine.commit(saved.proposal_id, "k2", caller="kai@example.com", spec_lookup=registry.get)).code == "verified"
    again = Talk("m7")
    again.session.issue(THREAD)
    with as_staff("mia-fixture"):
        text, refused = await call(again, "gmail_send_reply", thread_id=THREAD)
    assert refused is None and "That draft is Kai's words" in text
