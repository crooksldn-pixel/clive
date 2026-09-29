"""Round 13: a reply goes only to the address its card showed the owner.

The round-12 deploy review, S2b-01. A message can ask for replies somewhere other than its
sender (a Reply-To header): a storefront contact form does it honestly, and a spoofed message
does it to take the answer. The write tools have always replied to the Reply-To when there is
one (`gmail_writes.thread_context`). The reply composer did not: it showed the message's From,
marked checked, and the reply prepared from it went to the Reply-To. Only the final hold card
named the real address.

What holds now:

* the composer shows the address the reply will actually go to, derived as the write tool
  derives it; when that is a Reply-To that differs from the sender, the card shows both and the
  owner must confirm the address before anything is prepared;
* the reply tools refuse, whoever calls them, when a reply composer for the thread is on the
  owner's screen and the thread's recipient is not what its card shows (or not yet confirmed);
* the staged reply carries the composer it was prepared from.

Held through the real routes: `POST /turn` with a scripted model making the calls Claude would,
and `POST /command` for the owner's taps. The mailbox is the in-memory Gmail of
tests/test_gmail_writes.py; every address is invented.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from app.clients.gmail import GmailClient
from app.memory import ENTITY
from app.memory import current as memory
from app.tools import gmail_tools, gmail_writes
from tests import test_gmail_writes as mailbox
from tests import test_r12_orders as r12
from tests.test_r12_orders import say, tap

# The app, the scripted model and the owner's headers of the round-12 order tests.
shop = r12.shop

THREAD = "1b3c5d7e9f0a2c4e"
SENDER = "ann.sender@example.com"
ELSEWHERE = "replies@elsewhere.example"


class _Service:
    """googleapiclient's chain over the fake inbox, as far as `gmail_read_thread` uses it: the
    same messages the write tools read, in the shape Gmail's API hands them over."""

    def __init__(self, inbox) -> None:
        self.inbox = inbox

    def users(self):
        return self

    def threads(self):
        return self

    def get(self, userId: str = "me", id: str = "", format: str = "full"):  # noqa: A002, N803
        messages = [{
            "id": m["id"], "labelIds": list(m["labels"]),
            "payload": {"headers": [{"name": k.title(), "value": v} for k, v in m["headers"].items()],
                        "mimeType": "text/plain",
                        "body": {"data": base64.urlsafe_b64encode(m["body"].encode()).decode()}},
        } for m in self.inbox.threads.get(id, [])]
        return SimpleNamespace(execute=lambda: {"messages": messages})


def message(*, reply_to: str = "", mid: str = "<m1@example.com>", id_: str = "m1") -> dict:
    return mailbox.msg(id_, from_=f"Ann Sender <{SENDER}>", reply_to=reply_to, subject="About my parcel",
                       mid=mid, labels=["INBOX"], body="Where is my parcel?")


@pytest.fixture()
async def mail(shop):
    """The inbox, wired where production wires it: the write tools, the read tools, and the
    runtime's own credential (which says what the owner's Gmail grant allows)."""
    inbox = mailbox.FakeGmail()
    inbox.threads = {THREAD: [message(reply_to=f"Elsewhere Desk <{ELSEWHERE}>")]}
    reader = GmailClient()
    reader._service = _Service(inbox)
    before = shop.runtime.gmail
    gmail_writes.bind(inbox, customer=None, policy=lambda: mailbox.Policy())
    gmail_tools.bind(reader)
    shop.runtime.gmail = inbox
    try:
        yield inbox
    finally:
        shop.runtime.gmail = before
        gmail_writes.bind(None)
        gmail_tools.bind(None)
        memory().drop(ENTITY, f"email_thread:{THREAD}")


async def read_the_thread(shop) -> dict:
    """He asks for the email; Claude reads the thread a search found (the search's issuing of
    the id is stood in for here)."""
    shop.runtime.sessions.get_or_create("g1").issue(THREAD)
    return await say(shop, "read me Ann's email", ("gmail_read_thread", {"thread_id": THREAD}))


def composer_of(body: dict) -> dict:
    (found,) = [i["data"] for i in body["ui"] if i["type"] == "email_compose"]
    return found


def pending(shop) -> list:
    return [p for p in shop.runtime.sessions.get("g1").proposals if p.status.value == "PENDING"]


async def open_reply(shop) -> dict:
    await read_the_thread(shop)
    composer = composer_of(await tap(shop, "compose.reply", thread_id=THREAD))
    typed = await tap(shop, "compose.field", compose_id=composer["compose_id"], field="body", value="It went out today.")
    assert typed["ok"], typed
    return composer


# ============================================================ what the card shows


async def test_the_read_thread_carries_where_replies_go_when_it_is_not_the_sender(shop, mail):
    body = await read_the_thread(shop)
    (read,) = [t for t in body["tool_calls"] if t["name"] == "gmail_read_thread"]
    assert read["ok"], read
    held = memory().get(ENTITY, f"email_thread:{THREAD}", allow_stale=True).value
    (only,) = held["messages"]
    assert only["from_email"] == SENDER and only["reply_to"] == {"email": ELSEWHERE, "name": "Elsewhere Desk"}, only
    assert {SENDER, ELSEWHERE, "Elsewhere Desk"} <= shop.runtime.sessions.get("g1").pii_seen, \
        "both addresses are remembered as personal data, so the logs scrub them"


async def test_a_reply_to_that_is_the_sender_is_not_mentioned(shop, mail):
    mail.threads = {THREAD: [message(reply_to=f"Ann <{SENDER}>")]}
    await read_the_thread(shop)
    (only,) = memory().get(ENTITY, f"email_thread:{THREAD}", allow_stale=True).value["messages"]
    assert "reply_to" not in only


@pytest.mark.parametrize("mode", ["send", "draft"])
async def test_the_tapped_reply_shows_where_it_goes_and_waits_for_him_to_confirm_it(shop, mail, mode):
    """The finding's own case, by touch. Before the repair the card said "Ann · her address",
    checked, and Send prepared a reply to the Reply-To."""
    composer = await open_reply(shop)
    to = composer["to"]
    assert to["value"] == ELSEWHERE and to["status"] == "uncertain", to
    assert SENDER in to["hint"], "both addresses are on the card"
    assert "confirm_to" in [a["id"] for a in composer["actions"]]

    refused = await tap(shop, "compose.stage", compose_id=composer["compose_id"], mode=mode)
    assert refused["ok"] is False and refused["code"] == "not_ready", refused
    assert ELSEWHERE in refused["detail"] and SENDER in refused["detail"], refused["detail"]
    assert pending(shop) == [] and not mail.drafts and not mail.sent

    confirmed = composer_of(await tap(shop, "compose.confirm_to", compose_id=composer["compose_id"]))
    assert confirmed["to"]["value"] == ELSEWHERE and confirmed["to"]["status"] == "ok"
    assert "confirm_to" not in [a["id"] for a in confirmed["actions"]]
    staged = await tap(shop, "compose.stage", compose_id=composer["compose_id"], mode=mode)
    assert staged["ok"], staged
    (proposal,) = pending(shop)
    assert proposal.execution["to"] == confirmed["to"]["value"] == ELSEWHERE
    assert proposal.execution["compose_id"] == composer["compose_id"], "the reply carries the card it came from"


async def test_a_reply_with_no_reply_to_is_the_sender_and_needs_no_confirming(shop, mail):
    mail.threads = {THREAD: [message()]}
    composer = await open_reply(shop)
    assert composer["to"]["value"] == SENDER and composer["to"]["status"] == "ok"
    assert "confirm_to" not in [a["id"] for a in composer["actions"]]
    staged = await tap(shop, "compose.stage", compose_id=composer["compose_id"], mode="send")
    assert staged["ok"], staged
    (proposal,) = pending(shop)
    assert proposal.execution["to"] == SENDER


# ============================================================ the tools hold it too


async def test_the_model_cannot_send_past_a_card_that_is_waiting_to_be_confirmed(shop, mail):
    """The model's door: the composer is up showing both addresses, and Claude calls the reply
    tool itself. Refused until the owner has confirmed on the card; prepared after."""
    await read_the_thread(shop)
    opened = await say(shop, "reply that it went out today",
                       ("gmail_compose_open", {"to": SENDER, "subject": "Re: About my parcel",
                                               "body": "It went out today.", "thread_id": THREAD}))
    composer = composer_of(opened)
    assert composer["to"]["value"] == ELSEWHERE and composer["to"]["status"] == "uncertain", composer["to"]
    said = await say(shop, "send it", ("gmail_send_reply", {"thread_id": THREAD, "body": "It went out today."}))
    (call,) = [t for t in said["tool_calls"] if t["name"] == "gmail_send_reply"]
    assert not call["ok"] and ELSEWHERE in call["error"], call
    assert pending(shop) == []

    await tap(shop, "compose.confirm_to", compose_id=composer["compose_id"])
    said = await say(shop, "send it", ("gmail_send_reply", {"thread_id": THREAD, "body": "It went out today."}))
    (proposal,) = pending(shop)
    assert proposal.execution["to"] == ELSEWHERE


async def test_a_card_that_guessed_the_recipient_cannot_be_sent_to_another(shop, mail):
    """A reply opened on a thread the Mac has not read: the card shows the address Claude gave,
    and the thread's own recipient is somebody else. Before the repair the reply was prepared
    to the thread's recipient under a card that had shown another."""
    shop.runtime.sessions.get_or_create("g1").issue(THREAD)
    composer = composer_of(await say(shop, "reply to Ann that it went out today",
                                     ("gmail_compose_open", {"to": SENDER, "subject": "Re: About my parcel",
                                                             "body": "It went out today.", "thread_id": THREAD})))
    assert composer["to"]["value"] == SENDER
    staged = await tap(shop, "compose.stage", compose_id=composer["compose_id"], mode="send")
    assert staged["ok"] is False and ELSEWHERE in staged["detail"] and SENDER in staged["detail"], staged
    assert pending(shop) == [] and not mail.sent


async def test_a_thread_that_changed_since_the_card_was_drawn_is_not_replied_to_elsewhere(shop, mail):
    """Read with no Reply-To, so the card shows the sender; then a message arrives asking for
    replies elsewhere. The reply would go there now, which is not what the card shows."""
    mail.threads = {THREAD: [message()]}
    composer = await open_reply(shop)
    assert composer["to"]["value"] == SENDER and composer["to"]["status"] == "ok"
    mail.threads[THREAD].append(message(reply_to=ELSEWHERE, mid="<m2@example.com>", id_="m2"))
    staged = await tap(shop, "compose.stage", compose_id=composer["compose_id"], mode="send")
    assert staged["ok"] is False and ELSEWHERE in staged["detail"], staged
    assert pending(shop) == [] and not mail.sent


async def test_a_draft_of_ours_waiting_in_the_thread_is_not_who_the_reply_is_to(shop, mail):
    """Gmail lists a draft in its thread. The newest message there is then our own draft, and
    the reply card took it for the one to answer: it showed our own address while the tool
    answered the customer — which the card is now held to, so it has to show the customer."""
    mail.threads = {THREAD: [message()]}
    raw = gmail_writes.build_raw(sender=mailbox.ME, sender_name="CROOKS", to=SENDER, to_name="Ann Sender",
                                 subject="Re: About my parcel", body="Draft.", token="<draft-2@crooksldn.com>",
                                 in_reply_to="<m1@example.com>")
    mail.create_draft(raw, THREAD)
    composer = await open_reply(shop)
    assert composer["to"]["value"] == SENDER and composer["to"]["status"] == "ok", composer["to"]
    staged = await tap(shop, "compose.stage", compose_id=composer["compose_id"], mode="send")
    assert staged["ok"], staged
    (proposal,) = pending(shop)
    assert proposal.execution["to"] == SENDER
