"""Email on the action engine: a reply drafted or sent in a customer's thread, a new email
to an order's customer, a thread archived. The card is the email; the recipient is read
from the thread or the order, never from the model; a message is found again by the
Message-ID minted here, so a send is proven from the thread and happens once. The inbox
is a fake in memory; nothing reaches a network."""

from __future__ import annotations

import base64
import copy
from email import message_from_bytes, policy
from types import SimpleNamespace

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.grammar import gesture_for
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients import gmail as gmail_client
from app.clients.gmail import (
    SCOPE_COMPOSE,
    SCOPE_MODIFY,
    SCOPE_READONLY,
    GmailClient,
    GmailError,
    ScopeReport,
)
from app.presentation import present_proposal_state
from app.session.models import Session
from app.tools import gmail_writes, registry
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from app.tools.registry import ToolError
from tests.fake_credentials import google_oauth_token

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

ORDER = "gid://shopify/Order/1930"
THREAD = "18f3a9c2b1d4e5f6"
ME = "team@crooksldn.com"
CUSTOMER = "daniel@example.com"
HOSTILE = "<img src=x onerror=alert(1)>"


class Policy:
    gmail_from_name = "CROOKS"
    gmail_signature = "CROOKS"
    gmail_link_hosts = "crooksldn.com,royalmail.com"


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def msg(id_: str, *, from_: str, subject: str, mid: str, labels: list[str], to: str = ME, auth: str = "dkim=pass header.i=@example.com", body: str = "hello", in_reply_to: str = "", references: str = "", reply_to: str = "") -> dict:
    headers = {"from": from_, "to": to, "subject": subject, "date": "Tue, 8 Sep 2026 10:12:00 +0100", "message-id": mid, "authentication-results": f"mx.google.com; {auth}" if auth else ""}
    if in_reply_to:
        headers["in-reply-to"] = in_reply_to
        headers["references"] = references
    if reply_to:
        headers["reply-to"] = reply_to
    return {"id": id_, "labels": list(labels), "headers": headers, "body": body}


INBOUND = msg("m1", from_="Daniel Stub <daniel@example.com>", subject="Order 1930 — where is it?", mid="<abc@example.com>", labels=["INBOX", "UNREAD"], body="Hi, any news on 1930?")


class FakeGmail(GmailClient):
    """An inbox in memory: threads of messages with labels and headers, drafts, sent mail.
    Sent mail can take a moment to show in the thread, as Gmail's does."""

    def __init__(self) -> None:
        super().__init__()
        self.report = ScopeReport(frozenset({SCOPE_MODIFY, SCOPE_COMPOSE}), "google", 1e12)
        self.threads: dict[str, list[dict]] = {THREAD: [copy.deepcopy(INBOUND)]}
        self.drafts: dict[str, dict] = {}     # draft_id -> {"message_id", "thread_id", "parsed"}
        self.calls: list[tuple] = []
        self.fail_send = False
        self.lose_answer = False
        self.rewrite_header = False           # Gmail replaces the Message-ID on the way out
        self.lag = 0                          # thread reads before a sent message shows
        self._pending: list[tuple[str, dict]] = []
        self._n = 0

    def scopes(self, *, fresh: bool = False) -> ScopeReport:
        return self.report

    def address(self) -> str:
        return ME

    # --- reads
    def _flush(self) -> None:
        if self._pending and self.lag <= 0:
            for thread_id, message in self._pending:
                self.threads.setdefault(thread_id, []).append(message)
            self._pending = []
        elif self._pending:
            self.lag -= 1

    def thread_messages(self, thread_id: str) -> list[dict]:
        self.calls.append(("thread", thread_id))
        self._flush()
        return copy.deepcopy(self.threads.get(thread_id) or [])

    def thread_labels(self, thread_id: str) -> set[str]:
        labels: set[str] = set()
        for m in self.threads.get(thread_id, []):
            labels.update(m["labels"])
        return labels

    def message_labels(self, message_id: str) -> set[str]:
        self.calls.append(("labels", message_id))
        self._flush()
        for ms in self.threads.values():
            for m in ms:
                if m["id"] == message_id:
                    return set(m["labels"])
        raise GmailError("Could not read the message: not found")

    def list_drafts(self, query: str) -> list[dict]:
        self.calls.append(("drafts", query))
        out = []
        for draft_id, d in self.drafts.items():
            parsed = d["parsed"]
            if query.startswith("rfc822msgid:") and parsed["message-id"].strip("<>") == query.split(":", 1)[1].split()[0]:
                out.append({"draft_id": draft_id, "message_id": d["message_id"], "thread_id": d["thread_id"]})
            elif query.startswith("in:draft to:") and query.split("to:", 1)[1] in parsed["to"]:
                out.append({"draft_id": draft_id, "message_id": d["message_id"], "thread_id": d["thread_id"]})
        return out

    def get_draft(self, draft_id: str) -> dict:
        if draft_id not in self.drafts:
            raise GmailError("Could not read the draft: not found")
        d = self.drafts[draft_id]
        headers = [{"name": k.title(), "value": v} for k, v in d["parsed"].items() if k != "body"]
        return {"id": draft_id, "message": {"id": d["message_id"], "threadId": d["thread_id"], "payload": {"headers": headers, "mimeType": "text/plain", "body": {"data": b64(d["parsed"]["body"])}}}}

    def find_messages(self, query: str) -> list[dict]:
        self.calls.append(("find", query))
        self._flush()
        token = query.split("rfc822msgid:", 1)[1].split()[0]
        return [{"id": m["id"], "thread_id": t} for t, ms in self.threads.items() for m in ms if m["headers"].get("message-id", "").strip("<>") == token and "SENT" in m["labels"]]

    # --- writes
    @staticmethod
    def _parse(raw: str) -> dict:
        parsed = message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)
        return {k: str(parsed.get(k.title(), "") or "") for k in ("from", "to", "cc", "bcc", "subject", "message-id", "in-reply-to", "references")} | {"body": parsed.get_content()}

    def _next(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def create_draft(self, raw: str, thread_id: str | None) -> dict:
        self.calls.append(("create_draft", thread_id))
        parsed = self._parse(raw)
        message_id = self._next("d")
        thread_id = thread_id or self._next("t")
        self.drafts[self._next("draft")] = {"message_id": message_id, "thread_id": thread_id, "parsed": parsed}
        self.threads.setdefault(thread_id, []).append(msg(message_id, from_=parsed["from"], to=parsed["to"], subject=parsed["subject"], mid=parsed["message-id"], labels=["DRAFT"], auth="", body=parsed["body"], in_reply_to=parsed["in-reply-to"], references=parsed["references"]))
        return {"draft_id": list(self.drafts)[-1], "message_id": message_id, "thread_id": thread_id}

    def delete_draft(self, draft_id: str) -> None:
        self.calls.append(("delete_draft", draft_id))
        d = self.drafts.pop(draft_id)
        self.threads[d["thread_id"]] = [m for m in self.threads.get(d["thread_id"], []) if m["id"] != d["message_id"]]

    def _sent(self, parsed: dict, thread_id: str | None) -> dict:
        message_id = self._next("s")
        thread_id = thread_id or self._next("t")
        mid = f"<gmail-{message_id}@mail.gmail.com>" if self.rewrite_header else parsed["message-id"]
        self._pending.append((thread_id, msg(message_id, from_=parsed["from"], to=parsed["to"], subject=parsed["subject"], mid=mid, labels=["SENT"], auth="", body=parsed["body"], in_reply_to=parsed["in-reply-to"], references=parsed["references"])))
        return {"message_id": message_id, "thread_id": thread_id}

    def send_message(self, raw: str, thread_id: str | None) -> dict:
        self.calls.append(("send", thread_id))
        if self.fail_send:
            raise GmailError("Could not send: refused")
        answer = self._sent(self._parse(raw), thread_id)
        if self.lose_answer:
            raise GmailError("Could not send: timed out")
        return answer

    def send_draft(self, draft_id: str) -> dict:
        self.calls.append(("send_draft", draft_id))
        if self.fail_send:
            raise GmailError("Could not send the draft: refused")
        d = self.drafts.pop(draft_id)
        self.threads[d["thread_id"]] = [m for m in self.threads.get(d["thread_id"], []) if m["id"] != d["message_id"]]
        answer = self._sent(d["parsed"], d["thread_id"])
        if self.lose_answer:
            raise GmailError("Could not send the draft: timed out")
        return answer

    def modify_thread(self, thread_id: str, *, add: list[str], remove: list[str]) -> None:
        self.calls.append(("modify", thread_id, tuple(add), tuple(remove)))
        for m in self.threads.get(thread_id, []):
            m["labels"] = [x for x in m["labels"] if x not in remove] + [x for x in add if x not in m["labels"]]

    @property
    def sent(self) -> list[dict]:
        self._flush()
        return [m for ms in self.threads.values() for m in ms if "SENT" in m["labels"]]


CUSTOMER_ID = "gid://shopify/Customer/7"


async def customer_of(order_id: str, customer_id: str = "") -> dict:
    if customer_id:
        assert customer_id == CUSTOMER_ID and not order_id
        return {"name": "Daniel Stub", "email": CUSTOMER, "label": ""}
    assert order_id == ORDER
    return {"name": "Daniel Stub", "email": CUSTOMER, "label": "#1930"}


@pytest.fixture()
def box():
    inbox = FakeGmail()
    gmail_writes.bind(inbox, customer=customer_of, policy=lambda: Policy())
    yield inbox
    gmail_writes.bind(None)


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    monkeypatch.setattr(gmail_writes, "SETTLE_POLL_S", 0.0)
    monkeypatch.setattr(gmail_writes, "SETTLE_S", 0.5)
    return e


@pytest.fixture()
def session():
    s = Session(session_id="c1")
    s.issue(ORDER, THREAD, CUSTOMER_ID)
    s.epoch = 1
    return s


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def stage(session, tool, **args):
    before = len(session.proposals)
    text = await dispatch(tool, args, session=session, timeout_s=5)
    return text, (session.proposals[-1] if len(session.proposals) > before else None)


async def tap(engine, proposal):
    return await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup)


async def hold(engine, proposal):
    armed, code = engine.arm(proposal.proposal_id, "c1")
    assert code == ""
    proposal.armed_at -= 1.0
    return await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)


def decoded(proposal) -> dict:
    return FakeGmail._parse(proposal.execution["raw"])


BODY = "Hi Daniel,\n\nIt's being packed today and ships tomorrow with Royal Mail Tracked 24."


# --------------------------------------------------------------------------- declaration


@pytest.mark.parametrize("name,tier,kind,gesture,mutation", [
    ("gmail_draft_reply", Tier.AMBER, "reversible", "tap_commit", "gmail:draft"),
    ("gmail_send_reply", Tier.RED, "irreversible", "hold_to_arm", "gmail:send"),
    ("gmail_draft_new", Tier.AMBER, "reversible", "tap_commit", "gmail:draft"),
    ("gmail_send_new", Tier.RED, "irreversible", "hold_to_arm", "gmail:send"),
    ("gmail_thread_archive", Tier.AMBER, "reversible", "tap_commit", "gmail:labels"),
])
def test_every_email_change_is_declared_with_its_tier_gesture_and_kind_of_call(name, tier, kind, gesture, mutation):
    spec = registry.get(name)
    assert spec.tier is tier and spec.write.complete and spec.write.kind == kind and spec.write.mutation == mutation
    assert gesture_for(tier.value, kind) == gesture
    assert (spec.write.undo is not None) == spec.write.reversible
    # The recipient is never the model's to invent, and a copy header is nobody's at all.
    #
    # Phase 3 restates the first half rather than dropping it (app/families/compose.py). The
    # two NEW-email tools take an explicit `to`: an address the owner dictated, which is the
    # one recipient Shopify cannot supply, and which is admitted ONLY with the compose_id of a
    # composer the gate has already held to this conversation — so an address still cannot
    # arrive from a model mid-sentence. A REPLY's recipient is still read from the thread, and
    # the checks for that are in tests/test_compose.py beside this one.
    assert "cc" not in spec.input_schema["properties"] and "bcc" not in spec.input_schema["properties"], "a copy header is nobody's"
    if name in ("gmail_draft_new", "gmail_send_new"):
        recipient = spec.input_schema["properties"]["to"]
        assert recipient["type"] == "string" and recipient["maxLength"] <= 254, "an address is one bounded line"
        assert "compose_id" in spec.issued_id_args, "an address must ride with an issued composer id"
    else:
        assert "to" not in spec.input_schema["properties"], "a reply's recipient is never the model's"


def test_the_gate_wants_issued_ids_and_refuses_a_recipient_argument():
    assert classify("gmail_draft_reply", {"thread_id": THREAD, "body": "x"}, issued_ids={THREAD}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify("gmail_draft_reply", {"thread_id": THREAD, "body": "x"}).disposition is Disposition.DENY
    assert classify("gmail_draft_reply", {"thread_id": THREAD, "body": "x", "to": "x@y.com"}, issued_ids={THREAD}).disposition is Disposition.DENY
    assert classify("gmail_send_reply", {"thread_id": THREAD, "order_id": ORDER}, issued_ids={THREAD}).disposition is Disposition.DENY, "an order the conversation never looked up"
    assert classify("gmail_send_new", {"order_id": ORDER}, issued_ids={ORDER}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify("gmail_thread_archive", {"thread_id": THREAD}, issued_ids={THREAD}).disposition is Disposition.STAGE_FOR_OWNER


# --------------------------------------------------------------------------- a reply, drafted


async def test_preparing_a_draft_reply_addresses_it_from_the_thread_and_saves_nothing(box, engine, session):
    text, proposal = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY, order_id=ORDER)
    assert text.startswith("PROPOSED") and "draft a reply to Daniel about order 1930" in text
    assert not [c for c in box.calls if c[0] in ("create_draft", "send")]
    parsed = decoded(proposal)
    assert parsed["to"] == "Daniel Stub <daniel@example.com>" and parsed["from"] == f"CROOKS <{ME}>"
    assert parsed["subject"] == "Re: Order 1930 — where is it?" and parsed["in-reply-to"] == "<abc@example.com>" and parsed["references"] == "<abc@example.com>"
    assert gmail_writes._MESSAGE_ID.match(parsed["message-id"]) and parsed["message-id"].endswith("@crooksldn.com>")
    assert parsed["body"].rstrip("\n") == BODY + "\n\nCROOKS"
    assert proposal.before == {"last": "m1", "drafts": 0, "sent": 0} and proposal.risk == "AMBER" and proposal.interaction == "tap_commit"
    words = registry.get("gmail_draft_reply").write.present(proposal)
    assert words["title"] == "Save a draft reply" and words["body"] == BODY + "\n\nCROOKS" and words["done_title"] == "Draft saved"
    facts = {f["label"]: f["value"] for f in words["facts"]}
    assert facts == {"To": "Daniel Stub <daniel@example.com>", "Subject": "Re: Order 1930 — where is it?", "Replying to": "daniel@example.com, 8 Sep 10:12 · verified sender", "Order": "#1930 · the customer on the order"}
    line = engine.ledger.read()[-1]
    assert line["facts"] == {"kind": "draft_reply", "reply": True, "draft_used": False, "chars": len(BODY + "\n\nCROOKS"), "verified_sender": True, "to_checked": True}
    assert "Daniel" not in str(line) and "packed" not in str(line)
    assert {"daniel@example.com", "Daniel Stub"} <= session.pii_seen


async def test_a_tap_saves_the_draft_once_and_the_undo_deletes_it(box, engine, session):
    _, proposal = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    result = await tap(engine, proposal)
    assert result.code == "verified" and result.spoken == "Draft saved to Daniel. It's in Gmail, not sent."
    assert len(box.drafts) == 1 and [c[0] for c in box.calls if c[0] in ("create_draft", "send")] == ["create_draft"]
    assert proposal.entity == {"kind": "email", "to": CUSTOMER, "subject": "Re: Order 1930 — where is it?", "body": BODY + "\n\nCROOKS", "state": "draft"}
    items = present_proposal_state(proposal)
    assert [i["type"] for i in items] == ["success", "email_draft"]
    assert items[0]["data"]["title"] == "Draft saved" and items[1]["data"]["state"] == "draft" and items[1]["data"]["body"] == BODY + "\n\nCROOKS"
    undo = engine.find(proposal.undo_id)
    assert undo is not None and undo.interaction == "tap_commit"
    assert registry.get("gmail_draft_reply").write.present(undo)["title"] == "Delete the draft"
    undone = await tap(engine, undo)
    assert undone.code == "verified" and undone.spoken == "Draft deleted." and box.drafts == {}
    assert present_proposal_state(undo)[0]["data"]["title"] == "Draft deleted"


async def test_a_reply_named_with_an_order_must_be_to_that_orders_customer(box, engine, session):
    box.threads[THREAD][0]["headers"]["from"] = "Someone Else <someone@else.com>"
    text, proposal = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY, order_id=ORDER)
    assert text.startswith("ERROR") and "someone@else.com, not the customer on order #1930" in text and proposal is None


async def test_a_thread_with_nothing_from_the_customer_cannot_be_replied_to(box, engine, session):
    box.threads[THREAD] = [msg("m9", from_=f"CROOKS <{ME}>", subject="Hello", mid="<x@crooksldn.com>", labels=["SENT"], auth="")]
    text, proposal = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    assert text.startswith("ERROR") and "no message from the customer" in text and proposal is None


@pytest.mark.parametrize("body,words", [
    ("", "no text"),
    ("Hi <b>Daniel</b>", "plain text"),
    ("Track it at https://evil.example/track/1", "not a site the store links to"),
])
async def test_the_body_is_plain_bounded_and_links_only_where_the_store_does(box, engine, session, body, words):
    text, proposal = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=body)
    assert text.startswith("ERROR") and words in text and proposal is None
    with pytest.raises(ToolError, match="longer than 2000"):
        gmail_writes.clean_body("x" * 2001)


async def test_a_link_to_the_carrier_is_allowed_and_the_sign_off_is_not_doubled(box, engine, session):
    body = "Track it at https://www.royalmail.com/track-your-item#/AB123456785GB\n\nCROOKS"
    text, proposal = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=body)
    assert text.startswith("PROPOSED") and decoded(proposal)["body"].rstrip("\n") == body


async def test_an_unverified_sender_is_printed_on_the_card(box, engine, session):
    box.threads[THREAD][0]["headers"]["authentication-results"] = "mx.google.com; dkim=fail"
    _, proposal = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    replying = [f for f in registry.get("gmail_draft_reply").write.present(proposal)["facts"] if f["label"] == "Replying to"][0]
    assert replying["value"].endswith("sender not verified") and replying["tone"] == "warn"


# --------------------------------------------------------------------------- a reply, sent


async def test_a_hold_sends_the_reply_once_and_proves_it_from_the_thread(box, engine, session):
    text, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY, order_id=ORDER)
    assert "send a reply to Daniel about order 1930" in text and proposal.risk == "RED" and proposal.interaction == "hold_to_arm"
    words = registry.get("gmail_send_reply").write.present(proposal)
    assert words["title"] == "Send the reply" and words["detail"] == "Sends now. It cannot be unsent." and words["body"] == BODY + "\n\nCROOKS"
    assert {f["label"]: f["value"] for f in words["facts"]}["From"] == ME
    result = await hold(engine, proposal)
    assert result.code == "verified" and result.spoken == "Reply sent to Daniel."
    assert len(box.sent) == 1 and box.sent[0]["headers"]["in-reply-to"] == "<abc@example.com>" and [c[0] for c in box.calls if c[0] == "send"] == ["send"]
    assert proposal.undo_id is None and proposal.status is ActionStatus.VERIFIED
    items = present_proposal_state(proposal)
    assert [i["type"] for i in items] == ["success", "email_draft"] and items[0]["data"]["title"] == "Reply sent" and items[1]["data"]["state"] == "sent"
    again = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)
    assert again.code == "already_executed" and len(box.sent) == 1


async def test_a_tap_without_the_hold_sends_nothing(box, engine, session):
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    result = await tap(engine, proposal)
    assert result.code == "not_armed" and box.sent == [] and proposal.status is ActionStatus.PENDING


async def test_send_it_sends_the_one_draft_prepared_here_and_prints_its_text(box, engine, session):
    _, draft = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    assert (await tap(engine, draft)).code == "verified"
    session.epoch += 1
    text, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD)
    assert text.startswith("PROPOSED"), text
    ex = dict(proposal.execution)
    assert ex["draft_id"] == list(box.drafts)[0] and ex["body"] == BODY + "\n\nCROOKS" and ex["token"] == draft.execution["token"]
    assert registry.get("gmail_send_reply").write.present(proposal)["body"] == BODY + "\n\nCROOKS"
    assert {k: proposal.before[k] for k in ("last", "drafts", "sent")} == {"last": "m1", "drafts": 1, "sent": 0} and proposal.before["draft_sha"]
    result = await hold(engine, proposal)
    assert result.code == "verified" and box.drafts == {} and len(box.sent) == 1
    assert [c[0] for c in box.calls if c[0] in ("send", "send_draft")] == ["send_draft"]


async def test_send_it_with_no_draft_or_two_drafts_is_refused(box, engine, session):
    text, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD)
    assert text.startswith("ERROR") and "no draft waiting in that thread" in text and proposal is None
    for _ in range(2):
        _, draft = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY + str(_))
        assert (await tap(engine, draft)).code == "verified"
        session.epoch += 1
    text, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD)
    assert text.startswith("ERROR") and "2 drafts" in text and proposal is None and box.sent == []


async def test_a_new_message_in_the_thread_makes_the_reply_stale(box, engine, session):
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    box.threads[THREAD].append(msg("m2", from_="Daniel Stub <daniel@example.com>", subject="Re: Order 1930", mid="<def@example.com>", labels=["INBOX"], body="Actually, cancel it."))
    result = await hold(engine, proposal)
    assert result.code == "stale" and box.sent == [] and result.spoken == "That thread or its draft changed since this was prepared. Nothing was sent."


async def test_a_lost_answer_is_settled_by_reading_the_thread(box, engine, session):
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    box.lose_answer = True
    result = await hold(engine, proposal)
    assert result.code == "verified" and len(box.sent) == 1 and [c[0] for c in box.calls if c[0] == "send"] == ["send"]


async def test_a_sent_message_that_shows_a_moment_later_is_waited_for(box, engine, session):
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    box.lag = 3
    result = await hold(engine, proposal)
    assert result.code == "verified" and len(box.sent) == 1


async def test_a_refusal_from_gmail_sends_nothing_and_says_so(box, engine, session):
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    box.fail_send = True
    result = await hold(engine, proposal)
    # Gmail's refusal and a lost answer look the same from here; the thread is read and shows
    # nothing sent, and the owner is told to look before trying again — never "sent".
    assert proposal.status is ActionStatus.UNVERIFIED and box.sent == [] and result.code == "unverified"
    assert result.spoken == "I couldn't confirm the reply went. Check Sent in Gmail before sending again."


async def test_an_already_sent_draft_cannot_be_sent_again(box, engine, session):
    _, draft = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    await tap(engine, draft)
    session.epoch += 1
    _, send = await stage(session, "gmail_send_reply", thread_id=THREAD)
    assert (await hold(engine, send)).code == "verified"
    session.epoch += 1
    text, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD)
    assert text.startswith("ERROR") and proposal is None and len(box.sent) == 1


# --------------------------------------------------------------------------- a new email


async def test_a_new_email_goes_to_the_orders_customer_and_nowhere_else(box, engine, session):
    text, proposal = await stage(session, "gmail_draft_new", order_id=ORDER, subject="Your CROOKS order 1930", body=BODY)
    assert "draft an email to Daniel about order 1930" in text
    parsed = decoded(proposal)
    assert parsed["to"] == "Daniel Stub <daniel@example.com>" and parsed["subject"] == "Your CROOKS order 1930" and parsed["in-reply-to"] == ""
    assert proposal.before == {"drafts": 0, "sent": 0}
    result = await tap(engine, proposal)
    assert result.code == "verified" and len(box.drafts) == 1 and list(box.drafts.values())[0]["thread_id"].startswith("t")
    undone = await tap(engine, engine.find(proposal.undo_id))
    assert undone.code == "verified" and box.drafts == {}


async def test_a_new_email_needs_a_subject_and_a_customer_with_an_address(box, engine, session):
    text, proposal = await stage(session, "gmail_draft_new", order_id=ORDER, subject="", body=BODY)
    assert text.startswith("ERROR") and "needs a subject" in text and proposal is None

    async def nobody(order_id, customer_id=""):
        return {"name": "", "email": "", "label": "#1930"}

    gmail_writes.bind(box, customer=nobody, policy=lambda: Policy())
    text, proposal = await stage(session, "gmail_send_new", order_id=ORDER, subject="Hi", body=BODY)
    assert text.startswith("ERROR") and "no email address" in text and proposal is None


async def test_send_it_sends_the_one_new_draft_for_that_customer(box, engine, session):
    _, draft = await stage(session, "gmail_draft_new", order_id=ORDER, subject="Your CROOKS order 1930", body=BODY)
    assert (await tap(engine, draft)).code == "verified"
    session.epoch += 1
    text, proposal = await stage(session, "gmail_send_new", order_id=ORDER)
    assert text.startswith("PROPOSED"), text
    ex = dict(proposal.execution)
    assert ex["draft_id"] and ex["subject"] == "Your CROOKS order 1930" and ex["body"] == BODY + "\n\nCROOKS"
    result = await hold(engine, proposal)
    assert result.code == "verified" and result.spoken == "Email sent to Daniel." and box.drafts == {} and len(box.sent) == 1


async def test_a_new_email_sent_outright_is_proven_by_search(box, engine, session):
    _, proposal = await stage(session, "gmail_send_new", order_id=ORDER, subject="Your CROOKS order 1930", body=BODY)
    box.lag = 2
    result = await hold(engine, proposal)
    assert result.code == "verified" and len(box.sent) == 1 and any(c[0] == "find" for c in box.calls)


# --------------------------------------------------------------------------- the inbox


async def test_archiving_leaves_the_inbox_and_the_undo_puts_it_back(box, engine, session):
    text, proposal = await stage(session, "gmail_thread_archive", thread_id=THREAD)
    assert "archive the thread Order 1930 — where is it?" in text and proposal.interaction == "tap_commit"
    facts = {f["label"]: f["value"] for f in registry.get("gmail_thread_archive").write.present(proposal)["facts"]}
    assert facts == {"Thread": "Order 1930 — where is it?", "From": "Daniel Stub <daniel@example.com>"}
    result = await tap(engine, proposal)
    assert result.code == "verified" and result.spoken == "Archived." and "INBOX" not in box.thread_labels(THREAD)
    undo = engine.find(proposal.undo_id)
    undone = await tap(engine, undo)
    assert undone.code == "verified" and undone.spoken == "It's back in the inbox." and "INBOX" in box.thread_labels(THREAD)
    text, proposal = await stage(session, "gmail_thread_archive", thread_id=THREAD)
    box.modify_thread(THREAD, add=[], remove=["INBOX"])
    assert (await tap(engine, proposal)).code == "stale"


# --------------------------------------------------------------------------- the credential


def test_a_scope_report_answers_per_kind_of_call():
    report = ScopeReport(frozenset({SCOPE_MODIFY, SCOPE_COMPOSE}), "google", 0.0)
    assert report.allows("read") and report.allows("draft") and report.allows("send") and report.allows("labels") and report.verified
    assert report.words() == "compose, modify (verified by Google)"
    only_read = ScopeReport(frozenset({SCOPE_READONLY}), "stored", 0.0)
    assert only_read.allows("read") and not only_read.allows("send") and not only_read.allows("draft") and not only_read.verified


def test_effective_scopes_come_from_google_first_and_the_stored_token_last(monkeypatch):
    granted = SimpleNamespace(granted_scopes=[SCOPE_MODIFY, SCOPE_COMPOSE], token="t", scopes=[SCOPE_READONLY])
    assert gmail_client.effective_scopes(granted) == (frozenset({SCOPE_MODIFY, SCOPE_COMPOSE}), "google")

    class Answer:
        status_code = 200

        @staticmethod
        def json():
            return {"scope": f"{SCOPE_MODIFY} {SCOPE_COMPOSE}", "expires_in": "3000"}

    asked = []
    import httpx

    def fake_get(url, params=None, timeout=None):
        asked.append((url, params, timeout))
        return Answer()

    monkeypatch.setattr(httpx, "get", fake_get)
    access = google_oauth_token("gmail-tokeninfo")
    fresh = SimpleNamespace(granted_scopes=None, token=access, scopes=[SCOPE_READONLY])
    assert gmail_client.effective_scopes(fresh) == (frozenset({SCOPE_MODIFY, SCOPE_COMPOSE}), "google")
    assert asked[0][0] == gmail_client.TOKENINFO_URL and asked[0][1] == {"access_token": access} and asked[0][2] == gmail_client.TOKENINFO_TIMEOUT_S

    def down(url, params=None, timeout=None):
        raise OSError("no network")

    monkeypatch.setattr(httpx, "get", down)
    assert gmail_client.effective_scopes(fresh) == (frozenset({SCOPE_READONLY}), "stored")


def test_the_credential_is_loaded_with_the_scopes_it_was_granted_not_a_list_written_here(monkeypatch):
    """A token authorised for modify and compose must not be asked for readonly on refresh:
    google-auth refuses that as "not all requested scopes were granted", and the owner would
    be told to re-authorise a perfectly good credential."""
    import json

    from google.oauth2.credentials import Credentials

    stored = {"token": "t", "refresh_token": "r", "client_id": "c", "client_secret": "s", "scopes": [SCOPE_MODIFY, SCOPE_COMPOSE]}
    monkeypatch.setattr(gmail_client, "_read_token_json", lambda: (json.dumps(stored), "test"))
    seen = {}

    @classmethod
    def from_info(cls, info, scopes=None):
        seen["scopes"] = scopes
        return SimpleNamespace(refresh_token="r", valid=True, expired=False, scopes=info.get("scopes"))

    monkeypatch.setattr(Credentials, "from_authorized_user_info", from_info)
    creds = gmail_client.load_credentials()
    assert seen["scopes"] is None and creds.scopes == [SCOPE_MODIFY, SCOPE_COMPOSE]
    assert gmail_client.stored_scopes() == frozenset({SCOPE_MODIFY, SCOPE_COMPOSE})


def test_health_names_the_account_and_what_google_says_it_may_do(box):
    box._service = SimpleNamespace(users=lambda: SimpleNamespace(getProfile=lambda userId: SimpleNamespace(execute=lambda: {"emailAddress": ME})))
    ok, detail = box.health()
    assert ok and detail == f"{ME} · compose, modify (verified by Google)"
    assert "read-only" not in detail and "readonly" not in detail


# --------------------------------------------------------------------------- who the reply goes to


async def test_a_reply_goes_where_the_message_asks_and_the_card_says_so(box, engine, session):
    """A storefront contact form delivers From the store's mailer with Reply-To the customer."""
    box.threads[THREAD] = [msg("m1", from_="Store contact <mailer@shopify.com>", reply_to="Daniel Stub <daniel@example.com>", subject="Order 1930 — where is it?", mid="<abc@example.com>", labels=["INBOX"], auth="dkim=pass header.i=@shopify.com")]
    text, proposal = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY, order_id=ORDER)
    assert text.startswith("PROPOSED"), text
    assert decoded(proposal)["to"] == "Daniel Stub <daniel@example.com>"
    facts = {f["label"]: f["value"] for f in registry.get("gmail_draft_reply").write.present(proposal)["facts"]}
    assert facts["To"] == "Daniel Stub <daniel@example.com>" and "replies go to daniel@example.com" in facts["Replying to"]


async def test_a_reply_to_that_diverts_from_the_customer_is_refused(box, engine, session):
    box.threads[THREAD][0]["headers"]["reply-to"] = "Someone <someone@else.com>"
    text, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY, order_id=ORDER)
    assert text.startswith("ERROR") and "someone@else.com (the message asks for replies there" in text and proposal is None


async def test_a_thread_with_two_people_in_it_needs_the_order_named(box, engine, session):
    box.threads[THREAD].append(msg("m2", from_="Sam Other <sam@other.example>", subject="Re: Order 1930", mid="<def@other.example>", labels=["INBOX"], auth="", body="I'm collecting it for Daniel"))
    text, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    assert text.startswith("ERROR") and "messages from 2 people" in text and proposal is None
    text, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY, order_id=ORDER)
    assert text.startswith("ERROR") and "would go to sam@other.example, not the customer on order #1930" in text and proposal is None


async def test_a_reply_with_no_order_named_says_the_recipient_was_not_checked(box, engine, session):
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    order = [f for f in registry.get("gmail_send_reply").write.present(proposal)["facts"] if f["label"] == "Order"][0]
    assert order["value"].startswith("not checked") and order["tone"] == "warn"


async def test_send_the_draft_prints_and_sends_the_drafts_own_recipient_or_refuses(box, engine, session):
    """The draft was written to Daniel; someone else writes into the thread; "send it" must not
    print one name and send to another."""
    _, draft = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    assert (await tap(engine, draft)).code == "verified"
    session.epoch += 1
    box.threads[THREAD].insert(1, msg("m2", from_="Sam Other <sam@other.example>", subject="Re: Order 1930", mid="<def@other.example>", labels=["INBOX"], auth="", body="collecting it"))
    text, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, order_id=ORDER)
    assert text.startswith("ERROR") and ("would go to sam@other.example" in text or "addressed to daniel@example.com" in text), text
    text, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD)
    assert text.startswith("ERROR") and "messages from 2 people" in text


async def test_a_draft_edited_in_gmail_after_the_card_makes_the_send_stale(box, engine, session):
    _, draft = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    assert (await tap(engine, draft)).code == "verified"
    session.epoch += 1
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD)
    assert proposal.before["draft_sha"] and dict(proposal.execution)["body"] == BODY + "\n\nCROOKS"
    facts = {f["label"]: f["value"] for f in registry.get("gmail_send_reply").write.present(proposal)["facts"]}
    assert facts["Draft"] == "the one waiting in Gmail, as it reads now" and facts["To"] == "Daniel Stub <daniel@example.com>"
    list(box.drafts.values())[0]["parsed"]["body"] = BODY + " Also, a full refund is on its way.\n\nCROOKS"
    result = await hold(engine, proposal)
    assert result.code == "stale" and box.sent == [], "the card is the email; an edited draft is a different email"


@pytest.mark.parametrize("header, value", [
    ("to", "Someone Else <someone.else@example.org>"), ("cc", "someone.else@example.org"),
    ("bcc", "someone.else@example.org"), ("subject", "Re: Order 1930 — refund agreed"),
])
async def test_a_draft_readdressed_in_gmail_after_the_card_makes_the_send_stale(box, engine, session, header, value):
    """[inbox] The review of 8 October (note 2): the card prints who the draft goes to and its subject
    as well as its words. Changing only its To in Gmail after the card was drawn (same words, same
    Message-ID) sent it to someone else, "verified". Recipients, subject and words are one
    fingerprint now, on the reply path as on the others."""
    _, draft = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    assert (await tap(engine, draft)).code == "verified"
    session.epoch += 1
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD)
    assert proposal is not None and proposal.before["draft_sha"]
    list(box.drafts.values())[0]["parsed"][header] = value
    result = await hold(engine, proposal)
    assert result.code == "stale" and box.sent == [] and not [c for c in box.calls if c[0] in ("send_draft", "send")]


async def test_a_new_email_draft_readdressed_after_the_card_makes_the_send_stale(box, engine, session):
    _, draft = await stage(session, "gmail_draft_new", order_id=ORDER, subject="Your CROOKS order 1930", body=BODY)
    assert (await tap(engine, draft)).code == "verified"
    session.epoch += 1
    _, proposal = await stage(session, "gmail_send_new", order_id=ORDER)
    assert proposal is not None and proposal.execution["draft_id"]
    list(box.drafts.values())[0]["parsed"]["to"] = "Someone Else <someone.else@example.org>"
    result = await hold(engine, proposal)
    assert result.code == "stale" and box.sent == [] and not [c for c in box.calls if c[0] in ("send_draft", "send")]


def resaved_in_gmail(box, draft_id: str = "") -> None:
    """Gmail saves the draft again — an attachment added to it, or only its HTML part edited — so its
    plain words and its headers read as they did, and Gmail has given it a new message id."""
    draft_id = draft_id or list(box.drafts)[0]
    d = box.drafts[draft_id]
    old, d["message_id"] = d["message_id"], d["message_id"] + "-saved"
    for messages in box.threads.values():
        for m in messages:
            if m["id"] == old:
                m["id"] = d["message_id"]


async def test_a_draft_saved_again_in_gmail_after_the_card_makes_the_reply_stale(box, engine, session):
    """[inbox] The re-review of 8 October (note 1): an attachment added, or an edit to the HTML part
    only, after the card was drawn changed nothing the fingerprint read. Gmail gives a draft a new
    message id on every save, and the fingerprint pins it: the hold is stale and nothing is sent."""
    _, draft = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    assert (await tap(engine, draft)).code == "verified"
    session.epoch += 1
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD)
    assert proposal is not None and proposal.execution["draft_id"]
    resaved_in_gmail(box)
    result = await hold(engine, proposal)
    assert result.code == "stale" and box.sent == [] and not [c for c in box.calls if c[0] in ("send_draft", "send")]


async def test_a_new_email_draft_saved_again_after_the_card_makes_the_send_stale(box, engine, session):
    _, draft = await stage(session, "gmail_draft_new", order_id=ORDER, subject="Your CROOKS order 1930", body=BODY)
    assert (await tap(engine, draft)).code == "verified"
    session.epoch += 1
    _, proposal = await stage(session, "gmail_send_new", order_id=ORDER)
    assert proposal is not None and proposal.execution["draft_id"]
    resaved_in_gmail(box)
    result = await hold(engine, proposal)
    assert result.code == "stale" and box.sent == [] and not [c for c in box.calls if c[0] in ("send_draft", "send")]


async def test_a_send_whose_message_id_gmail_rewrote_is_proven_by_the_id_gmail_gave_back(box, engine, session):
    box.rewrite_header = True
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    result = await hold(engine, proposal)
    assert result.code == "verified" and len(box.sent) == 1 and proposal.sent["message_id"] == box.sent[0]["id"]
    assert "sent_message_id" not in dict(proposal.execution), "the staged action is immutable; Gmail's answer lives on the proposal"


async def test_a_new_email_can_go_to_a_customer_with_no_visible_order(box, engine, session):
    text, proposal = await stage(session, "gmail_draft_new", customer_id=CUSTOMER_ID, subject="Your size swap", body=BODY)
    assert text.startswith("PROPOSED") and decoded(proposal)["to"] == "Daniel Stub <daniel@example.com>"
    facts = {f["label"]: f["value"] for f in registry.get("gmail_draft_new").write.present(proposal)["facts"]}
    assert facts["Order"] == "the customer's record in Shopify"
    text, proposal = await stage(session, "gmail_draft_new", order_id=ORDER, customer_id=CUSTOMER_ID, subject="x", body=BODY)
    assert text.startswith("ERROR") and "which order — or, without one, which customer" in text
    text, proposal = await stage(session, "gmail_draft_new", subject="x", body=BODY)
    assert text.startswith("REFUSED") and "requires one of order_id, customer_id" in text


async def test_a_draft_to_a_sender_nobody_vouched_for_is_held_unless_an_order_ties_them(box, engine, session):
    box.threads[THREAD][0]["headers"]["authentication-results"] = "mx.google.com; spf=pass"
    _, proposal = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    assert proposal.risk == "RED" and proposal.interaction == "hold_to_arm"
    session.epoch += 1
    _, tied = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY, order_id=ORDER)
    assert tied.risk == "AMBER" and tied.interaction == "tap_commit"


async def test_archiving_keeps_the_subject_off_the_ledger(box, engine, session):
    box.threads[THREAD][0]["headers"]["subject"] = "Jane Smith — please send order 1930 to 12 Baker Street instead"
    _, proposal = await stage(session, "gmail_thread_archive", thread_id=THREAD)
    assert proposal.entity_label == "thread"
    assert (await tap(engine, proposal)).code == "verified"
    assert all("Baker" not in str(line) and "Jane" not in str(line) for line in engine.ledger.read())
