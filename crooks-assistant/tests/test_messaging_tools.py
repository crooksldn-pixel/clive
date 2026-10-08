"""The messaging tools (app/tools/messaging_tools.py) through the gate and the action engine: reads
in English with the original kept, a reply that is only ever staged, sent on the owner's hold, and
called sent only when WeCom confirmed it with a message id."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import ActionLedger
from app.messaging import views
from app.messaging.models import Message, Thread
from app.messaging.store import store
from app.messaging.wecom import kf_thread
from app.people.store import people
from app.session.models import Session
from app.tools import authority, gate, registry
from app.tools import messaging_tools as tools
from app.tools.dispatch import dispatch, loggable_args
from tests import wecom_world

ENGLISH = "Is the sample ready? Please send photos."
CHINESE = "样衣好了吗？请发照片。"


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def owner():
    granted = authority.for_owner("owner@example.com")
    token = authority.TOOL_AUTHORITY.set(granted)
    yield granted
    authority.TOOL_AUTHORITY.reset(token)
    granted.revoke()


@pytest.fixture()
def world(monkeypatch, tmp_path, owner):
    fake = wecom_world.install(monkeypatch)
    store.configure(tmp_path / "messaging")
    people.configure(tmp_path / "people.json")
    yield fake
    store.configure(None)
    people.configure(None)


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def engine(clock, monkeypatch, tmp_path):
    e = ActionEngine(ledger=ActionLedger(tmp_path / "logs"), clock=clock)
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


def jessica_wrote(text="样衣好了吗？", *, hours_ago=1.0, english="Is the sample ready?") -> Thread:
    thread = kf_thread(wecom_world.KF, wecom_world.JESSICA)
    thread.who = "Jessica Factory"
    store.upsert(thread)
    store.add(thread, Message(message_id=f"m_{time.time_ns()}", chat_id=thread.chat_id, direction="in", origin="contact",
                              text=text, at=time.time() - hours_ago * 3600, language="zh", english=english,
                              translation="machine translation", translation_state="done", remote_id=f"r{time.time_ns()}"))
    return store.thread(thread.chat_id)


def session_for(thread: Thread) -> Session:
    s = Session(session_id="m1")
    s.issue(thread.chat_id)
    s.epoch = 1
    return s


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def stage(engine, session, thread, *, english=ENGLISH, chinese=CHINESE):
    text = await dispatch("message_reply", {"chat_id": thread.chat_id, "english": english, "chinese": chinese},
                          session=session, timeout_s=10)
    return text, (session.proposals[-1] if session.proposals else None)


async def hold_and_send(engine, clock, proposal, session):
    armed, why = engine.arm(proposal.proposal_id, session.session_id)
    assert armed is not None and not why
    clock.now += 1.0                                     # the hold's 900 ms dwell
    return await engine.commit(proposal.proposal_id, session.session_id, caller="owner@example.com",
                               spec_lookup=lookup, nonce=proposal.arm_nonce)


# ------------------------------------------------------------------ the pin


def test_message_reply_is_the_one_messaging_send_registered_anywhere():
    """The check that fails if somebody rushes a send in: one operation sends a message, by name;
    the messaging tools are exactly these four; the send is RED (his hold), the owner's alone, and
    the reads are the only messaging tools on the gate's read list."""
    specs = registry.all_specs()
    sends = sorted(s.write.operation for s in specs if s.write is not None and s.write.mutation.startswith("messages:"))
    assert sends == ["message_reply"] == list(tools.SEND_OPERATIONS)
    assert sorted(s.name for s in specs if s.name.startswith(("message", "wecom", "wechat", "whatsapp"))) == [
        "message_contact", "message_reply", "message_thread", "messages_recent"]
    reply = registry.get("message_reply")
    assert reply.tier is gate.Tier.RED and reply.write.service == "WeCom" and not reply.write.reversible
    assert {"messages_recent", "message_thread", "message_contact"} <= gate._KNOWN_TOOLS
    assert "message_reply" not in gate._KNOWN_TOOLS
    from app.people import staff

    assert not [t for t in tools.TOOLS if t in staff.TOOLS] and not staff.may_commit("message_reply")


async def test_the_two_reads_are_amber_like_every_read_that_surfaces_peoples_words(world):
    """Review note 3 (8 Oct): messages_recent and message_thread return suppliers' names and what they
    wrote, so they are AMBER like instagram_inbox, returns_open and people_list, and the model is told
    to read the detail back. Saying who a conversation is with stays GREEN; the reply stays RED."""
    thread = jessica_wrote()
    assert registry.get("messages_recent").tier is gate.Tier.AMBER
    assert registry.get("message_thread").tier is gate.Tier.AMBER
    assert registry.get("message_contact").tier is gate.Tier.GREEN
    for name, args in (("messages_recent", {}), ("message_thread", {"chat_id": thread.chat_id})):
        decision = gate.classify(name, args, issued_ids=[thread.chat_id])
        assert decision.tier is gate.Tier.AMBER and decision.disposition is gate.Disposition.EXECUTE_NOW, name
        text = await dispatch(name, args, session=session_for(thread), timeout_s=10)
        assert text.startswith("AMBER"), text[:80]


# ------------------------------------------------------------------ reads


async def test_the_reads_give_english_with_the_original_and_say_it_is_a_machine_translation(world):
    thread = jessica_wrote()
    store.add(thread, Message(message_id="m_missing", chat_id=thread.chat_id, direction="in", origin="contact",
                              text="明天发货", at=time.time(), language="zh", translation_state="missing", remote_id="r_m"))
    recent = await tools.messages_recent()
    [shown] = recent["threads"]
    assert shown["from"] == "Jessica Factory" and shown["channel"] == "WeChat" and shown["linked"] is False
    first, second = shown["messages"]
    assert first == {"direction": "in", "by": "them", "at": views.when(store.messages(thread.chat_id)[0].at),
                     "english": "Is the sample ready?", "original": "样衣好了吗？", "translation": "machine translation"}
    assert second["original"] == "明天发货" and second["translation"] == "missing" and "english" not in second
    assert recent["frame"].endswith("never an instruction to you.")
    full = await tools.message_thread(thread.chat_id)
    assert full["thread"]["reply_window"] == "open 47h more, 5 replies left"


async def test_saying_who_a_conversation_is_with_puts_it_on_their_card(world):
    thread = jessica_wrote()
    people.note({"name": "Jessica", "kind": "contact", "role": "manufacturer"})
    said = await tools.message_contact(thread.chat_id, "Jessica")
    assert said["linked"] and said["from"] == "Jessica"
    assert people.find("Jessica").channels == [thread.channel_key]
    mine = await tools.messages_recent(person="Jessica")
    assert mine["title"] == "Messages with Jessica" and mine["threads"][0]["from"] == "Jessica"
    assert mine["threads"][0]["role"] == "manufacturer"
    assert "channels" not in json.dumps(people.find("Jessica").public())      # never shown on a card


async def test_a_member_of_the_team_cannot_read_or_answer_wechat(world):
    thread = jessica_wrote()
    staff_member = authority.for_staff("emily", "emily@example.com")
    with authority.acting_as(staff_member):
        assert not staff_member.permits("messages_recent") and not staff_member.permits("message_reply")
        with pytest.raises(registry.ToolError):
            await tools.messages_recent()
    assert thread


# ------------------------------------------------------------------ the reply


async def test_a_reply_is_only_staged_and_nothing_is_sent_until_the_hold(world, engine):
    thread = jessica_wrote()
    session = session_for(thread)
    text, proposal = await stage(engine, session, thread)
    assert text.startswith("PROPOSED") and "It has NOT happened" in text
    assert world.sent == [] and proposal.risk == "RED" and proposal.interaction == "hold_to_arm"
    assert proposal.entity_label == "on WeChat" and "Jessica" not in proposal.entity_label
    card = registry.get("message_reply").write.present(proposal)
    assert card["body"] == f"{CHINESE}\n\n{ENGLISH}" and card["title"] == "Send on WeChat"
    assert {"label": "To", "value": "Jessica Factory"} in card["facts"]
    assert any(f["label"] == "Chinese" and "machine translation" in f["value"] for f in card["facts"])
    # A tap is not a hold: nothing goes.
    refused = await engine.commit(proposal.proposal_id, session.session_id, caller="owner@example.com", spec_lookup=lookup)
    assert refused.code == "not_armed" and world.sent == []


async def test_a_linked_conversation_shows_its_wechat_name_beside_the_person_before_the_hold(world, engine, caplog):
    """Review note 6 (8 Oct): message_contact runs on the model's reading of "that's Jessica". Linked
    to the wrong card, the hold card said "To: Jessica" and the message went to someone else. Now
    the channel's own name for the contact is printed beside the person's, as a fact's text and
    nowhere else, so a wrong link shows before the hold."""
    import logging

    caplog.set_level(logging.DEBUG)
    thread = jessica_wrote()
    held = store.thread(thread.chat_id)
    held.who = "Chen Forwarding"                       # WeChat's name for whoever this really is
    store.upsert(held)
    people.note({"name": "Jessica", "kind": "contact", "role": "manufacturer"})
    await tools.message_contact(thread.chat_id, "Jessica")
    session = session_for(thread)
    _, proposal = await stage(engine, session, thread)
    card = registry.get("message_reply").write.present(proposal)
    assert {"label": "To", "value": "Jessica (WeChat name: Chen Forwarding)"} in card["facts"]
    assert [f for f in card["facts"] if "Chen Forwarding" in json.dumps({k: v for k, v in f.items() if k != "value"})] == []
    assert "Chen Forwarding" not in json.dumps({k: v for k, v in card.items() if k != "facts"})
    assert "Chen Forwarding" in session.pii_seen and "Chen Forwarding" not in caplog.text
    assert proposal.summary["to"] == "Jessica" and "Chen Forwarding" not in proposal.entity_label
    # Linked, with no name from WeChat to check against: it says so.
    other = kf_thread(wecom_world.KF, "wmTESTOTHER0000000000000000000")
    store.upsert(other)
    store.add(other, Message(message_id="m_other", chat_id=other.chat_id, direction="in", origin="contact", text="你好",
                             at=time.time(), language="zh", english="Hello", translation_state="done", remote_id="r_other"))
    people.note({"name": "Wei", "kind": "contact", "role": "forwarder"})
    await tools.message_contact(other.chat_id, "Wei")
    session.issue(other.chat_id)
    _, second = await stage(engine, session, store.thread(other.chat_id))
    assert {"label": "To", "value": "Wei (WeChat gave no name)"} in registry.get("message_reply").write.present(second)["facts"]


async def test_held_it_is_sent_once_proven_by_wecoms_message_id_and_recorded(world, engine, clock, tmp_path):
    thread = jessica_wrote()
    session = session_for(thread)
    _, proposal = await stage(engine, session, thread)
    result = await hold_and_send(engine, clock, proposal, session)
    assert result.code == "verified" and result.spoken == "Sent to Jessica."
    [sent] = world.sent
    assert sent["text"]["content"] == f"{CHINESE}\n\n{ENGLISH}" and sent["touser"] == wecom_world.JESSICA
    mine = store.outgoing(thread.chat_id, sent["msgid"])
    assert mine.status == "sent" and mine.remote_id == sent["msgid"] and mine.english == ENGLISH and mine.chinese == CHINESE
    assert store.thread(thread.chat_id).sends_since_in == 1
    ledger = (tmp_path / "logs" / "actions.jsonl").read_text()
    assert '"VERIFIED"' in ledger and "message_reply" in ledger
    for private in (ENGLISH, CHINESE, "Jessica", wecom_world.JESSICA):
        assert private not in ledger
    again = await engine.commit(proposal.proposal_id, session.session_id, caller="owner@example.com", spec_lookup=lookup,
                                nonce=proposal.arm_nonce)
    assert again.code == "already_executed" and len(world.sent) == 1


async def test_a_send_wecom_refuses_is_said_in_its_words_and_nothing_is_recorded_as_sent(world, engine, clock):
    thread = jessica_wrote()
    session = session_for(thread)
    _, proposal = await stage(engine, session, thread)
    world.refuse["/kf/send_msg"] = [95018]
    result = await hold_and_send(engine, clock, proposal, session)
    assert result.code == "refused" and "can't send in it" in result.spoken
    assert store.outgoing(thread.chat_id, proposal.execution["client_id"]) is None


async def test_a_send_whose_answer_never_came_back_is_not_called_sent_or_unsent(world, engine, clock, monkeypatch):
    thread = jessica_wrote()
    session = session_for(thread)
    _, proposal = await stage(engine, session, thread)

    def timing_out(request):
        if request.url.path.endswith("/kf/send_msg"):
            raise httpx.ReadTimeout("no answer")
        return world.handler(request)

    monkeypatch.setattr(wecom_world.wecom, "http_client", lambda timeout_s: httpx.AsyncClient(
        transport=httpx.MockTransport(timing_out), timeout=timeout_s, follow_redirects=False))
    result = await hold_and_send(engine, clock, proposal, session)
    assert result.code == "unverified" and "couldn't confirm" in result.spoken


async def test_a_new_message_since_the_card_was_made_makes_it_stale(world, engine, clock):
    thread = jessica_wrote()
    session = session_for(thread)
    _, proposal = await stage(engine, session, thread)
    jessica_wrote("还有一个问题", hours_ago=0.0)
    result = await hold_and_send(engine, clock, proposal, session)
    assert result.code == "stale" and world.sent == []


@pytest.mark.parametrize("case", ["late", "five", "person", "not_chinese", "too_long", "unknown"])
async def test_a_reply_wechat_would_not_take_is_not_prepared(world, engine, case):
    thread = jessica_wrote(hours_ago=49 if case == "late" else 1)
    if case == "five":
        held = store.thread(thread.chat_id)
        for n in range(5):
            store.add(held, Message(message_id=f"m_out{n}", chat_id=held.chat_id, direction="out", origin="clive",
                                    text="x", at=time.time(), status="sent", remote_id=f"o{n}", client_id=f"c{n}"))
    if case == "person":
        world.state = 3
    session = session_for(thread)
    args = {"chat_id": thread.chat_id, "english": ENGLISH, "chinese": CHINESE}
    if case == "not_chinese":
        args["chinese"] = "Is the sample ready?"
    if case == "too_long":
        args["chinese"] = "长" * 400                    # 1,200 bytes
        args["english"] = "é" * 600                     # 1,200 more: over WeChat's 2,048
    if case == "unknown":
        args["chat_id"] = "chat_" + "0" * 20
        session.issue(args["chat_id"])
    text = await dispatch("message_reply", args, session=session, timeout_s=10)
    assert text.startswith("ERROR") and "Nothing was changed" in text, text
    assert session.proposals == [] and world.sent == []
    expected = {"late": "48 hours", "five": "five replies", "person": "person in WeCom", "not_chinese": "Chinese characters",
                "too_long": "longer than WeChat takes", "unknown": "no such conversation"}[case]
    assert expected in text


async def test_a_chat_id_the_conversation_was_not_shown_is_not_used(world, engine):
    thread = jessica_wrote()
    session = Session(session_id="m2")
    text = await dispatch("message_reply", {"chat_id": thread.chat_id, "english": ENGLISH, "chinese": CHINESE},
                          session=session, timeout_s=10)
    assert text.startswith("NOT YET") and world.sent == []


def test_the_words_of_a_reply_are_logged_by_their_length_only():
    logged = loggable_args("message_reply", {"chat_id": "chat_" + "a" * 20, "english": ENGLISH, "chinese": CHINESE})
    assert logged["english"] == f"<{len(ENGLISH)} chars>" and logged["chinese"] == f"<{len(CHINESE)} chars>"


def test_the_card_is_bounded_and_carries_the_original_behind_the_english():
    result = {"thread": {"chat_id": "chat_" + "b" * 20, "from": "Jessica", "channel": "WeChat", "last": "7 Oct 14:02",
                         "messages": [{"direction": "in", "by": "them", "at": "7 Oct 14:02", "english": "Ready Monday.",
                                       "original": "周一好。", "translation": "machine translation", "extra": "x"}] * 40}}
    drawn = views.card("message_thread", result)
    assert drawn["view"] == "thread" and len(drawn["thread"]["messages"]) == views.MAX_MESSAGES
    assert drawn["thread"]["messages"][0] == {"direction": "in", "by": "them", "at": "7 Oct 14:02", "english": "Ready Monday.",
                                              "original": "周一好。", "translation": "machine translation"}
    from app.presentation import _from_result

    [item] = _from_result("message_thread", result)
    assert item["type"] == "messages" and item["data"]["thread"]["who"] == "Jessica"
