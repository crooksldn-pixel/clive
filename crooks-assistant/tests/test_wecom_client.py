"""app/clients/wecom.py against a stand-in WeCom (tests/wecom_world.py): tokens held and refreshed
as WeCom says, errcodes in plain words, and a send counted only when WeCom gave a message id."""

from __future__ import annotations

import logging

import pytest

from app.clients import wecom
from tests.wecom_world import JESSICA, KF, SECRET, install


async def test_one_token_serves_many_calls_and_is_asked_for_again_before_it_runs_out(monkeypatch):
    fake = install(monkeypatch)
    now = [1_000_000.0]
    monkeypatch.setattr(wecom, "TOKENS", wecom.Tokens(clock=lambda: now[0]))
    await wecom.agent()
    await wecom.agent()
    assert fake.minted == 1
    now[0] += 7200 - wecom.TOKEN_EARLY_S + 1          # inside the last five minutes of its life
    await wecom.agent()
    assert fake.minted == 2
    used = [params.get("access_token") for path, params, _ in fake.calls if path == "/agent/get"]
    assert used == ["token-1", "token-1", "token-2"]


@pytest.mark.parametrize("code", [40014, 42001, 42009])
async def test_a_refused_token_is_replaced_once_and_the_call_tried_once_more(monkeypatch, code):
    fake = install(monkeypatch)
    fake.refuse["/agent/get"] = [code]
    answer = await wecom.agent()
    assert answer["name"] == "CLIVE" and fake.minted == 2
    fake.refuse["/agent/get"] = [code, code]
    with pytest.raises(wecom.WeComError) as refused:
        await wecom.agent()
    assert refused.value.errcode == code and refused.value.refused
    assert len([c for c in fake.calls if c[0] == "/agent/get"]) == 2 + 2   # each: the call, and one more; never a third


def test_errcodes_are_plain_english_and_wecoms_own_text_is_not_repeated():
    assert "Trusted IPs" in wecom.words_for(60020, "not allow to access from your ip, hint: [x], from ip: 203.0.113.7")
    assert "203.0.113.7" in wecom.words_for(60020, "from ip: 203.0.113.7, more info at https://open.work.weixin.qq.com")
    assert "48 hours" in wecom.words_for(95002) and "five" in wecom.words_for(95001)
    assert "可调用接口的应用" in wecom.words_for(48002)
    unknown = wecom.words_for(123456, "secret hint abc123 from ip: 1.2.3.4")
    assert unknown == "WeCom said no (error 123456)." and "hint" not in unknown
    for code, words in wecom.ERRCODE_WORDS.items():
        assert words and words[0].isupper() and words.endswith("."), code


async def test_a_trusted_ip_refusal_names_the_address_to_add(monkeypatch):
    fake = install(monkeypatch)
    fake.errmsg = "not allow to access from your ip, from ip: 198.51.100.4, more info at https://open.work.weixin.qq.com"
    fake.refuse["/agent/get"] = [60020]
    with pytest.raises(wecom.WeComError) as refused:
        await wecom.agent()
    assert "198.51.100.4" in str(refused.value) and "企业可信IP" in str(refused.value)


async def test_a_wrong_secret_says_so(monkeypatch):
    fake = install(monkeypatch)
    fake.refuse["/gettoken"] = [40001]
    with pytest.raises(wecom.WeComError) as refused:
        await wecom.agent()
    assert refused.value.errcode == 40001 and "Secret" in str(refused.value)


async def test_a_customer_service_send_counts_only_with_a_message_id(monkeypatch):
    fake = install(monkeypatch)
    assert await wecom.send_kf_text(KF, JESSICA, "样衣好了吗？\n\nIs the sample ready?", msgid="cliveabc123") == "cliveabc123"
    sent = fake.sent[-1]
    assert sent == {"touser": JESSICA, "open_kfid": KF, "msgid": "cliveabc123", "msgtype": "text",
                    "text": {"content": "样衣好了吗？\n\nIs the sample ready?"}}
    fake.answers["/kf/send_msg"] = {"msgid": ""}
    with pytest.raises(wecom.WeComError) as unconfirmed:
        await wecom.send_kf_text(KF, JESSICA, "hello", msgid="clivedef456")
    assert "isn't counted as sent" in str(unconfirmed.value)
    del fake.answers["/kf/send_msg"]
    fake.refuse["/kf/send_msg"] = [95002]
    with pytest.raises(wecom.WeComError) as late:
        await wecom.send_kf_text(KF, JESSICA, "hello", msgid="cliveghi789")
    assert late.value.refused and "48 hours" in str(late.value)
    with pytest.raises(wecom.WeComError):
        await wecom.send_kf_text(KF, JESSICA, "长" * 700, msgid="clivejkl000")     # 2,100 bytes: refused, never cut
    with pytest.raises(wecom.WeComError):
        await wecom.send_kf_text(KF, JESSICA, "hello", msgid="not a valid id!")


async def test_an_app_message_to_a_member_wecom_names_invalid_is_not_a_send(monkeypatch):
    fake = install(monkeypatch)
    assert await wecom.send_member_text("Emily", "Parcel 2106 went today?") == "appmsg1"
    assert fake.sent[-1]["enable_duplicate_check"] == 1 and fake.sent[-1]["agentid"] == 1000002
    fake.answers["/message/send"] = {"msgid": "appmsg2", "invaliduser": "emily"}
    with pytest.raises(wecom.WeComError) as refused:
        await wecom.send_member_text("Emily", "hello")
    assert refused.value.refused and "visible range" in str(refused.value)


async def test_values_being_tried_have_tokens_of_their_own(monkeypatch):
    fake = install(monkeypatch)
    await wecom.agent()
    with wecom.trying({**fake.values, wecom.APP_SECRET: "a-different-secret"}):
        await wecom.token_check()
        assert wecom.value(wecom.APP_SECRET) == "a-different-secret"
    assert wecom.value(wecom.APP_SECRET) == SECRET
    secrets_sent = [params.get("corpsecret") for path, params, _ in fake.calls if path == "/gettoken"]
    assert secrets_sent == [SECRET, "a-different-secret"]
    await wecom.agent()
    assert fake.minted == 2                             # the token in use was untouched


async def test_no_secret_token_or_message_reaches_the_log(monkeypatch, caplog):
    fake = install(monkeypatch)
    caplog.set_level(logging.DEBUG)
    fake.refuse["/kf/send_msg"] = [95001]
    with pytest.raises(wecom.WeComError):
        await wecom.send_kf_text(KF, JESSICA, "秘密的样衣价格 £12", msgid="clive000111")
    fake.refuse["/gettoken"] = [40001]
    wecom.forget()
    with pytest.raises(wecom.WeComError):
        await wecom.agent()
    logged = caplog.text
    for private in (SECRET, "token-1", "秘密", JESSICA, KF):
        assert private not in logged
