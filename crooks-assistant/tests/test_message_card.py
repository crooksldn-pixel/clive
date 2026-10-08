"""The message card: one card, its words editable on it, one hold that sends (DEC-067).

George, 7 October 2026: "why do I have to click save draft and then say send it and then it pulls
up a send it screen to send." A message he asks for is now one card. These hold it end to end:

* the card the reply lands on carries the message block the tablet draws (`app/presentation.py
  _message_block`), with the contract the messaging tools will use (`app/families/message.py`);
* an edit on the card withdraws the waiting change and prepares the same write again with the new
  words, through the gate and the write tool's own checks — so the hold always sends the words on
  the card, and an edit the tool refuses leaves nothing that could send the old ones;
* the hold sends exactly those words and is proven by reading them back in the thread;
* "Save as draft" is the quiet other way, never the step he has to go through;
* the composer's Send becomes that card in the composer's place: no second screen.

The first half runs on the fake inbox of tests/test_gmail_writes.py, which can send; the second
through `POST /command` on the golden world (`experience/harness.py`), which cannot, and so holds
everything up to the hold.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import commands
from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.families import message as message_card
from app.presentation import present
from app.providers.base import ToolCall
from app.session.models import Session
from app.tools import gmail_writes
from app.tools.dispatch import dispatch
from experience.harness import harness
from tests.test_gmail_writes import (
    BODY,
    CUSTOMER,
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

pytestmark = pytest.mark.usefixtures("owner_asking")

EDITED = "Hi Daniel,\n\nGood news: it went out this morning with Royal Mail Tracked 24."
ROOT = Path(__file__).resolve().parent.parent


# The inbox, the engine and the conversation the email tests use, built here so that this
# file's names are its own (see tests/test_gmail_writes.py for the world they describe).
@pytest.fixture()
def box():
    inbox = FakeGmail()
    gmail_writes.bind(inbox, customer=customer_of, policy=lambda: Policy())
    yield inbox
    gmail_writes.bind(None)


@pytest.fixture()
def engine(monkeypatch):
    made = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", made)
    monkeypatch.setattr(gmail_writes, "SETTLE_POLL_S", 0.0)
    monkeypatch.setattr(gmail_writes, "SETTLE_S", 0.5)
    return made


@pytest.fixture()
def session():
    conversation = Session(session_id="c1")
    conversation.issue(ORDER, THREAD, CUSTOMER_ID)
    conversation.epoch = 1
    return conversation


def _press(actions, conversation, **args):
    """A finger on the card, as `POST /command` runs it: the command, then the staging it asks for."""
    ctx = commands.Ctx(SimpleNamespace(actions=actions), conversation, conversation.branch(), {k: str(v) for k, v in args.items()})
    return message_card._message_stage(ctx)


async def _prepare(conversation, outcome):
    """What `POST /command` does with the command's `stage`: the named write, through dispatch."""
    staging = outcome.changed["stage"]
    before = len(conversation.proposals)
    text = await dispatch(staging["tool"], dict(staging["args"]), session=conversation, timeout_s=5)
    made = conversation.proposals[-1] if len(conversation.proposals) > before else None
    # And what the route tells the message family once it has prepared it (`_tap`).
    message_card.prepared(staging, made.proposal_id if made is not None else "")
    return text, made


def _card(proposal, conversation):
    (item,) = [i for i in present([ToolCall(name=proposal.tool_name, args={}, ok=True, proposal_id=proposal.proposal_id)],
                                  session=conversation) if i["type"] == "confirmation"]
    return item["data"]


# --------------------------------------------------------------------------- the card


async def test_the_reply_card_is_the_message_and_the_hold_that_sends_it(box, engine, session):
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY, order_id=ORDER)
    data = _card(proposal, session)
    message = data["message"]
    assert message["channel"] == "email" and message["kind"] == "reply" and message["sending"] is True
    assert message["body"] == BODY and message["sign_off"] == "CROOKS", "the words as given; the sign-off said as that"
    assert message["editable"] == ["body"] and message["command"] == "message.stage"
    assert message["key"] == message_card.key_of(proposal) and message["key"].startswith("msg_")
    assert CUSTOMER not in message["key"] and THREAD not in message["key"], "the key carries nothing of who it is to"
    assert message["other"] == {"label": "Save as draft", "args": f"key={message['key']}&other=1"}
    assert data["interaction"]["kind"] == "hold_to_arm" and data["interaction"]["label"] == "Hold, then tap to send"
    assert data["risk"] == "red"


async def test_a_send_of_the_draft_waiting_in_gmail_is_that_draft_and_not_edited_here(box, engine, session):
    await tap(engine, (await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY))[1])
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD)
    message = _card(proposal, session)["message"]
    assert message["editable"] == [] and message["other"] is None and BODY in message["body"]


async def test_a_settled_card_offers_no_keyboard_and_no_other_way(box, engine, session):
    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    engine.revoke_ids([proposal.proposal_id], "test")
    message = _card(proposal, session)["message"]
    assert message["editable"] == [] and message["other"] is None


# --------------------------------------------------------------------------- the edit, then the hold


async def test_the_hold_sends_the_words_as_edited_on_the_card_and_proves_them(box, engine, session):
    _, first = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    key = message_card.key_of(first)
    out = _press(engine, session, compose_id=key, field="body", value=EDITED)
    assert out.ok, out.detail
    assert first.status is ActionStatus.REVOKED, "the old words can no longer be what a hold sends"
    staging = out.changed["stage"]
    assert staging["tool"] == "gmail_send_reply" and staging["args"]["body"] == EDITED and staging["revoke"] == []
    assert staging["message_key"] == key and staging["edit_seq"] >= 1
    text, second = await _prepare(session, out)
    assert text.startswith("PROPOSED") and second.risk == "RED" and second.interaction == "hold_to_arm"
    assert message_card.key_of(second) == key, "the same message, the same card"
    assert _card(second, session)["message"]["body"] == EDITED
    assert message_card.moved_since(session, staging) == "", "the newest edit is the card"

    result = await hold(engine, second)
    assert result.code == "verified" and result.spoken == "Reply sent to Daniel."
    (sent,) = box.sent
    assert sent["body"].rstrip("\n") == EDITED + "\n\nCROOKS", "exactly the words on the card, signed off"
    assert [c[0] for c in box.calls if c[0] in ("send", "create_draft", "send_draft")] == ["send"]


async def test_an_edit_the_write_refuses_leaves_nothing_that_could_send_the_old_words(box, engine, session):
    _, first = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    out = _press(engine, session, compose_id=message_card.key_of(first), field="body",
                 value="Track it at https://evil.example/track/1")
    text, second = await _prepare(session, out)
    assert text.startswith("ERROR") and "not a site the store links to" in text and second is None
    assert first.status is ActionStatus.REVOKED
    assert not [p for p in session.proposals if p.status is ActionStatus.PENDING], "nothing waits that the card does not show"
    assert box.sent == []


async def test_an_unchanged_field_draws_the_same_card_again(box, engine, session):
    _, first = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    out = _press(engine, session, compose_id=message_card.key_of(first), field="body", value=f"  {BODY}\n")
    assert out.ok and "stage" not in out.changed and out.changed["unchanged"] is True
    assert [c.proposal_id for c in out.calls] == [first.proposal_id] and first.status is ActionStatus.PENDING


async def test_only_the_fields_the_write_names_are_reached_by_a_keystroke(box, engine, session):
    _, first = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    key = message_card.key_of(first)
    for field in ("to", "subject", "thread_id", "order_id"):
        out = _press(engine, session, compose_id=key, field=field, value="someone@else.example")
        assert not out.ok and out.code == "not_editable", field
    assert first.status is ActionStatus.PENDING
    assert not _press(engine, session, compose_id=key, field="body", value="   ").ok, "a message needs words"
    assert _press(engine, session, compose_id="msg_0000000000000000", field="body", value=EDITED).code == "no_message"
    assert _press(engine, session, compose_id="prop_x", field="body", value=EDITED).code == "no_message"


async def test_an_edit_overtaken_by_a_later_one_is_not_the_card(box, engine, session):
    _, first = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    key = message_card.key_of(first)
    older = _press(engine, session, compose_id=key, field="body", value="first try")
    _, middle = await _prepare(session, older)
    newer = _press(engine, session, compose_id=key, field="body", value=EDITED)
    assert message_card.moved_since(session, older.changed["stage"]) == "A later edit is being prepared."
    _, last = await _prepare(session, newer)
    assert message_card.moved_since(session, newer.changed["stage"]) == ""
    assert middle.status is ActionStatus.REVOKED and last.status is ActionStatus.PENDING
    assert message_card.others_waiting(session, key, keep=last.proposal_id) == []


async def test_an_edit_while_the_one_before_it_is_being_prepared_is_told_to_wait(box, engine, session, monkeypatch):
    """Review note 2, the Mac's half: the first edit withdraws the waiting card before the new one
    exists, and a second edit in that gap was told "That message is no longer waiting". It is
    told "busy" now, and goes through once the first has been prepared."""
    _, first = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    key = message_card.key_of(first)
    a = _press(engine, session, compose_id=key, field="body", value="Hi Daniel, it went out today.")
    assert a.ok and message_card.preparing(key)
    b = _press(engine, session, compose_id=key, field="body", value=EDITED)
    assert not b.ok and b.code == "busy", (b.code, b.detail)
    _, after_a = await _prepare(session, a)
    assert not message_card.preparing(key), "the route said it was prepared"
    b = _press(engine, session, compose_id=key, field="body", value=EDITED)
    assert b.ok, b.detail
    _, after_b = await _prepare(session, b)
    assert after_a.status is ActionStatus.REVOKED and after_b.status is ActionStatus.PENDING
    assert message_card.key_of(after_b) == key and _card(after_b, session)["message"]["body"] == EDITED
    # A mark the route never cleared (a preparing that died) stops counting.
    assert _press(engine, session, compose_id=key, field="body", value="Hi Daniel, one more go.").ok
    assert message_card.preparing(key)
    later = message_card._clock() + message_card.PREPARING_S + 1
    monkeypatch.setattr(message_card, "_clock", lambda: later)
    assert not message_card.preparing(key)


async def test_two_messages_to_one_thread_are_two_cards_and_an_edit_of_one_leaves_the_other(box, engine, session):
    """Review note 7: two cards on the same thread — two replies he asked for — are two messages.
    They used to share a key (conversation, thread), so an edit of the first re-prepared the
    newest of them and the route then withdrew the other."""
    _, first = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    _, second = await stage(session, "gmail_send_reply", thread_id=THREAD, body=EDITED)
    assert first.status is ActionStatus.PENDING and second.status is ActionStatus.PENDING
    key = message_card.key_of(first)
    assert key != message_card.key_of(second), "two messages, two cards"
    out = _press(engine, session, compose_id=key, field="body", value="Hi Daniel,\n\nIt is on its way to you today.")
    assert out.ok, out.detail
    assert first.status is ActionStatus.REVOKED and second.status is ActionStatus.PENDING, "the edit is of the card it was typed on"
    assert out.changed["stage"]["args"]["body"].endswith("It is on its way to you today.")
    _, edited = await _prepare(session, out)
    assert message_card.key_of(edited) == key, "the edited card is still the first message"
    assert message_card.others_waiting(session, key, keep=edited.proposal_id) == [], "nothing of the other message is withdrawn"
    assert second.status is ActionStatus.PENDING


# --------------------------------------------------------------------------- the other way


async def test_save_as_draft_is_the_quiet_other_way_and_withdraws_the_send_only_once_it_exists(box, engine, session):
    _, send = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    out = _press(engine, session, key=message_card.key_of(send), other="1")
    staging = out.changed["stage"]
    assert staging["tool"] == "gmail_draft_reply" and staging["revoke"] == [send.proposal_id]
    assert send.status is ActionStatus.PENDING, "withdrawn by the route only once the draft is prepared"
    _, draft = await _prepare(session, out)
    assert draft.risk == "AMBER" and draft.interaction == "tap_commit"
    message = _card(draft, session)["message"]
    assert message["sending"] is False and message["other"]["label"] == "Send instead"
    result = await tap(engine, draft)
    assert result.code == "verified" and len(box.drafts) == 1 and box.sent == []


async def test_send_instead_on_a_draft_card_is_the_send_held_as_outward(box, engine, session):
    _, draft = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    out = _press(engine, session, key=message_card.key_of(draft), other="1")
    assert out.changed["stage"]["tool"] == "gmail_send_reply"
    _, send = await _prepare(session, out)
    assert send.risk == "RED" and send.interaction == "hold_to_arm", "sending to a customer is outward: the hold"
    assert (await tap(engine, send)).code == "not_armed" and box.sent == []


# --------------------------------------------------------------------------- a send that did not go


async def _refused(box, engine, session, why: str = "Invalid To header"):
    """An edited reply held, and Gmail answering no: the engine settles it FAILED, refused."""
    from app.clients.gmail import GmailRefused

    _, first = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    _, held = await _prepare(session, _press(engine, session, compose_id=message_card.key_of(first), field="body", value=EDITED))

    def refuse(raw, thread_id):
        box.calls.append(("send", thread_id))
        raise GmailRefused(why)

    box.send_message = refuse
    result = await hold(engine, held)
    return held, result


async def test_a_send_gmail_refused_says_not_sent_and_why_and_offers_the_same_words_again(box, engine, session):
    from app.presentation import present_action

    held, result = await _refused(box, engine, session)
    assert held.status is ActionStatus.FAILED and result.code == "refused" and box.sent == []
    (card,) = present_action(result, session=session)
    assert card["type"] == "error" and card["data"]["title"] == "Not sent"
    assert card["data"]["recovery"] == "Gmail refused it: Invalid To header. Nothing was sent.", card["data"]["recovery"]
    key = message_card.key_of(held)
    assert card["data"]["again"] == {"label": "Try again", "command": "message.stage", "args": f"key={key}&again=1"}

    out = _press(engine, session, key=key, again="1")
    assert out.ok, out.detail
    staging = out.changed["stage"]
    assert staging["tool"] == "gmail_send_reply" and staging["args"]["body"] == EDITED and staging["revoke"] == []
    _, again = await _prepare(session, out)
    assert again.status is ActionStatus.PENDING and again.risk == "RED" and again.interaction == "hold_to_arm"
    assert _card(again, session)["message"]["body"] == EDITED, "the words as they were on the card he held"
    assert box.sent == [], "trying again prepares the card; only the hold sends"
    assert not _press(engine, session, key=key, again="1").ok, "never a second card over the one waiting"


async def test_google_s_own_reason_is_said_without_the_request_or_the_exception(box, engine, session):
    held, _ = await _refused(box, engine, session, why='Could not send: <HttpError 400 when requesting [url] returned "Invalid To header". Details: "[]">')
    assert message_card.why_not_sent(held) == "Gmail refused it: Invalid To header."


async def test_a_send_that_may_have_gone_never_offers_to_send_again(box, engine, session):
    from app.presentation import present_action

    _, proposal = await stage(session, "gmail_send_reply", thread_id=THREAD, body=BODY)
    box.fail_send = True
    result = await hold(engine, proposal)
    assert proposal.status is ActionStatus.UNVERIFIED
    (card,) = present_action(result, session=session)
    assert "again" not in card["data"] and card["data"]["title"] == "Could not confirm"
    out = _press(engine, session, key=message_card.key_of(proposal), again="1")
    assert not out.ok and out.code == "not_again"


# --------------------------------------------------------------------------- through POST /command


PRIYAS_THREAD = "c28cf65d31fe6cbb"
REPLY = "Hi Priya, yes: the black cap is the adjustable one."


@pytest.fixture()
async def world():
    async with harness(admitted=True) as h:
        yield h


def _confirmations(capture) -> list[dict]:
    return [i["data"] for i in capture.ui if i.get("type") == "confirmation"]


async def test_an_edit_on_the_glass_is_the_card_again_in_its_place(world):
    said = await world.ask("reply to priya", ("gmail_search", {"query": "cap"}),
                           ("gmail_send_reply", {"thread_id": PRIYAS_THREAD, "body": REPLY}), session_id="edit")
    (card,) = _confirmations(said)
    key = card["message"]["key"]
    edited = await world.touch("message.stage", session_id="edit", compose_id=key, field="body",
                               value="Hi Priya, it is adjustable, one size fits all.")
    assert edited.raw["ok"] is True, edited.raw
    first = edited.ui[0]
    assert first["type"] == "confirmation", "the new card comes first, where the old one was"
    assert first["data"]["message"]["body"] == "Hi Priya, it is adjustable, one size fits all."
    assert first["data"]["message"]["key"] == key and first["data"]["proposal_id"] != card["proposal_id"]
    held = world.runtime.sessions.get("edit")
    states = {p.proposal_id: p.status.value for p in held.proposals}
    assert states[card["proposal_id"]] == "REVOKED" and states[first["data"]["proposal_id"]] == "PENDING"


async def test_the_composers_send_is_the_message_card_in_its_place(world):
    await world.ask("what did priya say", ("gmail_search", {"query": "cap"}),
                    ("gmail_read_thread", {"thread_id": PRIYAS_THREAD}), session_id="cmp")
    opened = await world.touch("compose.reply", session_id="cmp", thread_id=PRIYAS_THREAD)
    compose_id = opened.raw["changed"]["compose_id"]
    typed = await world.touch("compose.field", session_id="cmp", compose_id=compose_id, field="body", value=REPLY)
    assert typed.raw["ok"] is True, typed.raw
    sent = await world.touch("compose.stage", session_id="cmp", compose_id=compose_id, mode="send")
    assert sent.raw["ok"] is True, sent.raw
    kinds = [i["type"] for i in sent.ui]
    assert "email_compose" not in kinds, f"the composer is not a second screen beside its own send: {kinds}"
    (card,) = _confirmations(sent)
    assert card["message"]["body"] == REPLY and card["message"]["editable"] == ["body"]
    assert card["interaction"]["kind"] == "hold_to_arm"


# --------------------------------------------------------------------------- the tablet's half


NODE = shutil.which("node") or ("/opt/node22/bin/node" if Path("/opt/node22/bin/node").exists() else None)


@pytest.mark.skipif(NODE is None, reason="node is not installed here")
def test_the_message_card_under_node():
    result = subprocess.run([NODE, "--test", str(ROOT / "tests" / "web" / "message-card.test.js")],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(NODE is None, reason="node is not installed here")
def test_typing_on_the_message_card_one_edit_at_a_time_under_node():
    """Review note 2, the tablet's half (web/app.js): a second edit waits for the first's answer,
    a timer that outlived a redraw finds the field that replaced its own, and "busy" goes again."""
    result = subprocess.run([NODE, "--test", str(ROOT / "tests" / "web" / "message-edit.test.js")],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
