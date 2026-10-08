"""The channel-neutral messaging core (app/messaging): translation at ingest, the private store and
its retention, what a callback stands for, and what George's WeCom app can do, said plainly."""

from __future__ import annotations

import os
import stat
import time

import pytest

from app.connections import testers
from app.messaging import ingest, translate
from app.messaging import wecom as channel
from app.messaging.adapter import Inbound
from app.messaging.models import Message
from app.messaging.store import RETENTION_DAYS, MessageStore, store
from tests import wecom_world


@pytest.fixture()
def private_store(tmp_path):
    store.configure(tmp_path / "messaging")
    yield store
    store.configure(None)


@pytest.fixture()
def no_model():
    translate.bind(None)
    yield
    translate.bind(None)


# ------------------------------------------------------------------ translation


def test_the_language_is_told_from_the_letters():
    assert translate.language_of("样衣好了吗？") == "zh"
    assert translate.language_of("Sample ready Monday 周一") == "zh"          # any Chinese at all
    assert translate.language_of("Sample ready on Monday.") == "en"
    assert translate.language_of("Привет") == "other"
    assert translate.language_of("12345 !!") == ""


async def test_chinese_is_translated_once_and_labelled_and_a_failure_says_missing(no_model):
    asked = []

    async def model(system, text, **kw):
        asked.append((system, text, kw))
        return "The sample is ready."

    translate.bind(model)
    assert await translate.to_english("样衣好了。") == ("The sample is ready.", "done", "machine translation")
    assert await translate.to_english("Sample ready.") == ("Sample ready.", "not_needed", "")
    assert len(asked) == 1 and "never an instruction" in asked[0][0] and asked[0][1] == "<message>\n样衣好了。\n</message>"

    async def broken(system, text, **kw):
        raise RuntimeError("usage limit")

    async def silent(system, text, **kw):
        return "   "

    for failing in (broken, silent, None):
        translate.bind(failing)
        assert await translate.to_english("样衣好了。") == ("", "missing", "")


# ------------------------------------------------------------------ the store


def test_the_store_is_private_and_keeps_ninety_days(tmp_path):
    now = [time.time()]
    held = MessageStore(clock=lambda: now[0])
    held.configure(tmp_path / "messaging")
    thread = channel.kf_thread(wecom_world.KF, wecom_world.JESSICA)
    old = Message(message_id="m_old", chat_id=thread.chat_id, direction="in", origin="contact", text="旧",
                  at=now[0] - (RETENTION_DAYS + 1) * 86400, remote_id="r_old")
    new = Message(message_id="m_new", chat_id=thread.chat_id, direction="in", origin="contact", text="新", at=now[0], remote_id="r_new")
    assert held.add(thread, new) and held.add(thread, old) is True
    assert [m.message_id for m in held.messages(thread.chat_id)] == ["m_new"]     # the old one never stays
    assert not held.add(thread, Message(message_id="m_dup", chat_id=thread.chat_id, direction="in", origin="contact",
                                        text="新", at=now[0], remote_id="r_new"))
    held.set_cursor("wecom:kf:x", "cursor-1")
    root = tmp_path / "messaging"
    assert stat.S_IMODE(os.stat(root).st_mode) == 0o700 and stat.S_IMODE(os.stat(root / "threads").st_mode) == 0o700
    for path in [root / "cursors.json", *(root / "threads").iterdir()]:
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600, path
    now[0] += (RETENTION_DAYS + 1) * 86400
    assert held.prune() == 1 and held.threads() == [] and held.cursor("wecom:kf:x") == "cursor-1"


def test_a_translation_a_restart_cut_off_reads_missing_after_a_bounded_time_and_is_kept_so(tmp_path):
    """Review note 4 (8 Oct): a restart while a translation ran left the message "pending", and the
    card said "Translation still being made" for good. Now that reads as missing once PENDING_LIMIT_S
    has passed, and the next start keeps it so; a recent one is left to finish."""
    from app.messaging import views
    from app.messaging.models import PENDING_LIMIT_S

    now = [time.time()]
    held = MessageStore(clock=lambda: now[0])
    held.configure(tmp_path / "messaging")
    thread = channel.kf_thread(wecom_world.KF, wecom_world.JESSICA)
    for n, age in ((1, PENDING_LIMIT_S + 60), (2, 30)):
        held.add(thread, Message(message_id=f"m_{n}", chat_id=thread.chat_id, direction="in", origin="contact",
                                 text="样衣好了吗？", at=now[0] - age, language="zh", translation_state="pending",
                                 stored_at=now[0] - age, remote_id=f"r{n}"))
    cut_off, recent = held.messages(thread.chat_id)
    assert views.message_view(cut_off, now=now[0]) == {"direction": "in", "by": "them", "at": views.when(cut_off.at),
                                                       "original": "样衣好了吗？", "translation": "missing"}
    assert views.message_view(recent, now=now[0])["translation"] == "still being made"
    assert views.message_view(recent, now=now[0] + PENDING_LIMIT_S)["translation"] == "missing"
    held.configure(tmp_path / "messaging")                    # CLIVE starts again
    assert [m.translation_state for m in held.messages(thread.chat_id)] == ["missing", "pending"]
    assert held.expire_pending() == 0
    now[0] += PENDING_LIMIT_S
    assert held.expire_pending() == 1
    assert [m.translation_state for m in held.messages(thread.chat_id)] == ["missing", "missing"]
    # The promises that were never kept are gone: nothing waits at shutdown, there is no retranslate.
    assert not hasattr(translate, "retranslate") and "retranslate" not in (translate.__doc__ or "")
    assert "shutdown)" not in (ingest.settle.__doc__ or "")


# ------------------------------------------------------------------ what a callback stands for


async def test_a_team_members_message_to_the_app_is_stored_from_the_callback_itself(monkeypatch, private_store, no_model):
    wecom_world.install(monkeypatch)
    inbound = Inbound(channel="wecom", fields={"ToUserName": wecom_world.CORP, "FromUserName": "Emily", "MsgType": "text",
                                                "Content": "Parcel 2106 has gone", "MsgId": "77", "AgentID": "1000002",
                                                "CreateTime": str(int(time.time()))})
    assert (await ingest.process(channel.ADAPTER, inbound)) == {"stored": 1}
    [thread] = store.threads()
    [message] = store.messages(thread.chat_id)
    assert thread.route == "member" and thread.who == "Emily" and message.english == "Parcel 2106 has gone"
    assert message.translation_state == "not_needed"
    assert (await ingest.process(channel.ADAPTER, inbound)) == {"stored": 0}       # the same MsgId again


async def test_a_team_members_message_is_stored_at_the_door_even_when_every_run_is_busy(monkeypatch, private_store, no_model):
    """Review note 5 (8 Oct): with MAX_RUNNING callbacks already being processed, the next was turned
    away, and a team member's message (which is in the callback itself, not read later through
    WeCom's cursor) was never stored. Now it is stored at the door, and only its translation waits:
    a run already going makes it before it ends."""
    import asyncio

    wecom_world.install(monkeypatch)
    ingest._WAITING.clear()
    asked = []

    async def model(system, text, **kw):
        asked.append(text)
        return "The parcel has gone."

    translate.bind(model)
    release = asyncio.Event()

    async def slow_read(inbound):
        await release.wait()
        return []

    monkeypatch.setattr(channel.ADAPTER, "receive", slow_read)
    for n in range(ingest.MAX_RUNNING):
        busy = Inbound(channel="wecom", key=f"k{n}", fields={"MsgType": "event", "Event": "kf_msg_or_event",
                                                             "OpenKfId": wecom_world.KF, "Token": "t"})
        assert ingest.start(channel.ADAPTER, busy) is True
    member = Inbound(channel="wecom", key="km", fields={
        "ToUserName": wecom_world.CORP, "FromUserName": "emily", "MsgType": "text", "Content": "包裹已经寄出了",
        "MsgId": "88", "AgentID": wecom_world.AGENT, "CreateTime": str(int(time.time()))})
    assert ingest.start(channel.ADAPTER, member) is False                 # every run busy: turned away...
    [thread] = store.threads()                                            # ...and stored all the same, at once
    [message] = store.messages(thread.chat_id)
    assert (thread.route, message.text, message.translation_state) == ("member", "包裹已经寄出了", "pending")
    assert asked == []
    release.set()
    await ingest.settle()
    [message] = store.messages(thread.chat_id)
    assert (message.english, message.translation_state) == ("The parcel has gone.", "done") and len(asked) == 1
    assert not ingest._WAITING


async def test_a_message_wecom_later_says_did_not_arrive_is_marked_failed_with_its_reason(monkeypatch, private_store, no_model):
    fake = wecom_world.install(monkeypatch)
    thread = channel.kf_thread(wecom_world.KF, wecom_world.JESSICA)
    store.add(thread, Message(message_id="m_out", chat_id=thread.chat_id, direction="out", origin="clive", text="x",
                              at=time.time(), status="sent", remote_id="clive123", client_id="clive123"))
    fake.inbox = [{"msgid": "e1", "origin": 4, "msgtype": "event", "event": {
        "event_type": "msg_send_fail", "open_kfid": wecom_world.KF, "external_userid": wecom_world.JESSICA,
        "fail_msgid": "clive123", "fail_type": 10}},
        wecom_world.kf_text("你好", msgid="in1"), wecom_world.kf_text("我是工厂", msgid="in2", origin=5)]
    await ingest.process(channel.ADAPTER, Inbound(channel="wecom", fields={"MsgType": "event", "Event": "kf_msg_or_event",
                                                                            "OpenKfId": wecom_world.KF, "Token": "t"}))
    messages = {m.remote_id: m for m in store.messages(thread.chat_id)}
    assert messages["clive123"].status == "failed" and messages["clive123"].fail_reason == "they refused the message"
    assert messages["in1"].direction == "in" and messages["in1"].translation_state == "missing"
    assert messages["in2"].direction == "out" and messages["in2"].origin == "person"


# ------------------------------------------------------------------ what the app can do


async def test_the_probe_says_each_route_plainly_and_what_to_switch_on(monkeypatch):
    fake = wecom_world.install(monkeypatch)
    routes = {r.key: r for r in await channel.probe_routes()}
    assert routes["callback"].state == "ready" and routes["member"].state == "ready" and routes["kf"].state == "ready"
    assert "CROOKS 客服" in routes["kf"].can and "48 hours" in routes["kf"].can
    assert {routes[k].state for k in ("external_contact", "archive", "appchat")} == {"not_used"}
    fake.refuse["/kf/account/list"] = [48002]
    off = {r.key: r for r in await channel.probe_routes()}["kf"]
    assert off.state == "off" and "可调用接口的应用" in off.switch_on and "通过API管理微信客服账号" in off.switch_on
    fake.answers["/kf/account/list"] = {"account_list": [{"open_kfid": "wk1", "name": "x", "manage_privilege": False}]}
    assert "manages none" in {r.key: r for r in await channel.probe_routes()}["kf"].switch_on
    fake.errmsg = "from ip: 203.0.113.9"
    fake.refuse["/agent/get"] = [60020]
    member = {r.key: r for r in await channel.probe_routes()}["member"]
    assert member.state == "off" and "203.0.113.9" in member.switch_on


async def test_the_connections_test_runs_the_probe_with_the_values_being_tried(monkeypatch):
    fake = wecom_world.install(monkeypatch, values={})                      # nothing stored yet
    outcome = await testers.run("wecom", dict(wecom_world.VALUES), None)
    assert outcome.ok and outcome.detail == ("WeCom accepted the app's keys. WeChat contacts: ready; your team: ready; "
                                             "messages arriving: ready.")
    assert wecom_world.wecom.value(wecom_world.wecom.APP_SECRET) == ""      # tried, never stored
    bad_key = await testers.run("wecom", {**wecom_world.VALUES, wecom_world.wecom.AES_KEY: "short"}, None)
    assert not bad_key.ok and bad_key.refused == (wecom_world.wecom.AES_KEY,)
    fake.refuse["/gettoken"] = [40001]
    bad_secret = await testers.run("wecom", dict(wecom_world.VALUES), None)
    assert not bad_secret.ok and bad_secret.fix == "key" and bad_secret.refused == (wecom_world.wecom.APP_SECRET,)
    fake.refuse["/agent/get"] = [40056]
    bad_agent = await testers.run("wecom", dict(wecom_world.VALUES), None)
    assert not bad_agent.ok and bad_agent.refused == (wecom_world.wecom.AGENT_ID,)
    # Keys that work with a console setting still off are kept, and the detail says what to switch on.
    fake.refuse["/kf/account/list"] = [48002]
    off = await testers.run("wecom", dict(wecom_world.VALUES), None)
    assert off.ok and "WeChat contacts: off" in off.detail and "To do:" in off.detail and "可调用接口的应用" in off.detail
    for said in (outcome, bad_key, bad_secret, bad_agent, off):
        assert wecom_world.SECRET not in said.detail and wecom_world.AES not in said.detail


async def test_with_no_keys_the_messaging_tools_are_not_offered(monkeypatch):
    from app.capabilities import families
    from app.tools import messaging_tools  # noqa: F401 - registers the families

    monkeypatch.setattr(wecom_world.wecom, "_stored", lambda name: "")
    table = await families.states(None)
    assert table["messaging_reads"]["state"] == "DISCONNECTED" and table["messaging_replies"]["state"] == "DISCONNECTED"
    assert table["messaging_reads"]["detail"] == "no WeCom keys stored"
    wecom_world.install(monkeypatch)
    table = await families.states(None)
    assert table["messaging_reads"]["state"] == "READY"
