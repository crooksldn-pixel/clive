"""Round 13: a change to the email on the screen withdraws what was prepared from it before.

The round-12 deploy review, S2b-03. Send on the composer prepares a hold card carrying the
email as it read at that moment. Retype the recipient, the subject or the words afterwards and
the composer changed while the hold card did not: holding it sent the old words to the old
address, which the old card named, but which was no longer what the owner was looking at.

Now every edit that changes the email withdraws, there and then, each change still waiting that
was prepared from it — a send or a draft, prepared by his tap or by the model — and the tablet
is told which, so it can settle those cards. An edit landing while a Send is still being
prepared withdraws that one as it arrives. Cancelling the composer withdraws them too. A
keystroke that changes nothing withdraws nothing.

Through the real `POST /command` and `POST /turn`, on the in-memory Gmail of
tests/test_gmail_writes.py. Every address is invented.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from app.tools.dispatch import dispatch
from tests import test_r12_orders as r12
from tests import test_r13_reply_recipient as rr
from tests.test_r12_orders import PROXIED, say, tap

shop = r12.shop
mail = rr.mail

ADDRESS = "location.scout@example.org"


def pending(shop) -> list:
    return [p for p in shop.runtime.sessions.get("g1").proposals if p.status.value == "PENDING"]


def status_of(shop, proposal_id: str) -> str:
    return shop.runtime.actions.find(proposal_id).status.value


async def reply_prepared(shop, mail) -> tuple[str, str]:
    """A reply to Ann, typed on the card and prepared to send: (composer, proposal)."""
    mail.threads = {rr.THREAD: [rr.message()]}
    composer = await rr.open_reply(shop)
    staged = await tap(shop, "compose.stage", compose_id=composer["compose_id"], mode="send")
    assert staged["ok"], staged
    return composer["compose_id"], staged["changed"]["proposal_id"]


async def new_email_prepared(shop, mode: str = "send") -> tuple[str, str]:
    """A new email to an address he gave, checked by his own typing, prepared: (composer, proposal)."""
    body = await say(shop, "email the location scout about Sunday",
                     ("gmail_compose_open", {"to": ADDRESS, "subject": "Sunday", "body": "Are you free on Sunday?"}))
    (composer,) = [i["data"] for i in body["ui"] if i["type"] == "email_compose"]
    ident = composer["compose_id"]
    assert (await tap(shop, "compose.field", compose_id=ident, field="to", value=ADDRESS))["ok"]
    staged = await tap(shop, "compose.stage", compose_id=ident, mode=mode)
    assert staged["ok"], staged
    return ident, staged["changed"]["proposal_id"]


async def hold(shop, proposal_id: str):
    armed = await shop.post(f"/actions/{proposal_id}/arm", data={"session_id": "g1"}, headers=PROXIED)
    if armed.status_code != 200:
        return armed
    shop.runtime.actions.find(proposal_id).armed_at -= 1.0
    return await shop.post(f"/actions/{proposal_id}/commit", data={"session_id": "g1"},
                           headers={**PROXIED, "X-Crooks-Arm": armed.json()["nonce"]})


@pytest.mark.parametrize("field,value", [("body", "Actually it goes out tomorrow.")])
async def test_retyping_a_prepared_reply_withdraws_it_and_the_old_words_are_never_sent(shop, mail, field, value):
    """The finding's own case, on a reply. Before the repair the hold card stayed PENDING and
    holding it sent "It went out today." after he had changed it."""
    ident, proposal = await reply_prepared(shop, mail)
    edited = await tap(shop, "compose.field", compose_id=ident, field=field, value=value)
    assert edited["ok"], edited
    assert status_of(shop, proposal) == "REVOKED"
    assert edited["changed"]["withdrawn"] == [proposal], "the tablet is told which card to settle"
    assert (await hold(shop, proposal)).status_code != 200 or status_of(shop, proposal) != "VERIFIED"
    assert not mail.sent, "the old words went nowhere"


@pytest.mark.parametrize("field,value", [("to", "someone.else@example.org"), ("subject", "Sunday, 10am"),
                                         ("body", "Are you free on Sunday morning?"), ("to_name", "Sam")])
async def test_retyping_any_part_of_a_prepared_email_withdraws_it(shop, mail, field, value):
    ident, proposal = await new_email_prepared(shop)
    edited = await tap(shop, "compose.field", compose_id=ident, field=field, value=value)
    assert edited["ok"] and status_of(shop, proposal) == "REVOKED", (field, edited)
    assert edited["changed"]["withdrawn"] == [proposal]


async def test_a_prepared_draft_is_withdrawn_the_same_way(shop, mail):
    ident, proposal = await new_email_prepared(shop, mode="draft")
    await tap(shop, "compose.field", compose_id=ident, field="body", value="Free on Saturday instead?")
    assert status_of(shop, proposal) == "REVOKED" and not mail.drafts


async def test_a_keystroke_that_changes_nothing_withdraws_nothing(shop, mail):
    ident, proposal = await new_email_prepared(shop)
    same = await tap(shop, "compose.field", compose_id=ident, field="subject", value="Sunday")
    assert same["ok"] and "withdrawn" not in same["changed"]
    assert status_of(shop, proposal) == "PENDING"


async def test_cancelling_the_email_withdraws_what_was_prepared_from_it(shop, mail):
    ident, proposal = await new_email_prepared(shop)
    gone = await tap(shop, "compose.discard", compose_id=ident)
    assert gone["ok"] and status_of(shop, proposal) == "REVOKED"
    assert gone["changed"]["withdrawn"] == [proposal]


@pytest.mark.usefixtures("owner_asking")
async def test_the_models_own_rewrite_of_the_email_withdraws_it_too(shop, mail):
    """The model writes into the composer (`gmail_compose_fill`) after a send was prepared from
    it. A spoken sentence already withdraws this half's waiting cards; the tool holds the same
    line on its own, so the rule does not rest on where it was called from."""
    ident, proposal = await new_email_prepared(shop)
    session = shop.runtime.sessions.get("g1")
    text = await dispatch("gmail_compose_fill", {"compose_id": ident, "subject": "Sunday", "body": "Free on Monday?"},
                          session=session, timeout_s=5)
    assert not text.startswith(("ERROR", "REFUSED")), text
    assert status_of(shop, proposal) == "REVOKED"


async def test_an_edit_that_lands_while_send_is_being_prepared_withdraws_that_send(shop, mail):
    """The owner taps Send and, while the Mac is still reading the thread to prepare it, types
    into the body. The send being prepared is of the words before the edit: it is withdrawn as it
    arrives, and the tap that asked for it says so."""
    mail.threads = {rr.THREAD: [rr.message()]}
    composer = await rr.open_reply(shop)
    ident = composer["compose_id"]
    reading, release = threading.Event(), threading.Event()
    real = mail.thread_messages

    def slow(thread_id):
        reading.set()
        release.wait(5)
        return real(thread_id)

    mail.thread_messages = slow
    staging = asyncio.create_task(shop.post("/command", data={"session_id": "g1", "command": "compose.stage",
                                                              "compose_id": ident, "mode": "send"}, headers=PROXIED))
    assert await asyncio.to_thread(reading.wait, 5)
    edited = await tap(shop, "compose.field", compose_id=ident, field="body", value="Tomorrow, not today.")
    assert edited["ok"]
    release.set()
    staged = (await asyncio.wait_for(staging, 5)).json()
    assert staged["ok"] is False and staged["code"] == "changed_meanwhile", staged
    assert pending(shop) == [], "nothing prepared from the old words is left to hold"
    assert not mail.sent
