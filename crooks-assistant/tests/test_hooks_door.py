"""The one public door, /hooks/wecom (app/routes/hooks.py, app/main.py): what WeCom signed gets in,
everything else gets an empty 403, and every other path is closed to the public exactly as before.

Through the real app and its middleware (the `client` fixture of tests/test_actions_routes.py),
with a stand-in WeCom (tests/wecom_world.py) sealing callbacks exactly as WeCom does.
"""

from __future__ import annotations

import logging
import time

import pytest

from app.main import app
from app.messaging import guard as guard_module
from app.messaging import ingest, translate
from app.messaging.store import store
from app.routes.hooks import HOOK_PATHS
from tests import wecom_world
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    OWNER,
    PROXIED,
    client,
    configure,
)

STRANGER = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}


@pytest.fixture()
def world(client, monkeypatch, tmp_path):  # noqa: F811
    fake = wecom_world.install(monkeypatch)
    store.configure(tmp_path / "messaging")
    guard_module.GUARD._seen.clear()
    said: list[str] = []

    async def fake_complete(system, text, **_kw):
        said.append(text)
        return "Is the sample ready? It goes out on Monday."

    translate.bind(fake_complete)
    fake.inbox = [wecom_world.kf_text("样衣好了吗？周一寄出。", msgid="from_msg_1")]
    yield fake, said
    translate.bind(None)
    store.configure(None)


def _closed_to_the_public(client):  # noqa: F811
    """Production's door: the owner's login listed, nothing on the server speaking for him."""
    configure(client, logins=OWNER, local=False)
    client.runtime.settings = client.runtime.settings.model_copy(update={"local_owner": False})
    app.state.allowed_logins = client.runtime.allowed_logins


async def test_the_hook_paths_are_exactly_one():
    assert HOOK_PATHS == frozenset({"/hooks/wecom"})


async def test_wecoms_url_check_is_answered_with_the_decrypted_echo(client, world):  # noqa: F811
    _closed_to_the_public(client)
    crypto = wecom_world.wecom.CallbackCrypto(wecom_world.TOKEN, wecom_world.AES, wecom_world.CORP)
    echo = crypto.encrypt("8812763309414513")
    stamp = str(int(time.time()))
    query = {"msg_signature": wecom_world.wecom.signature(wecom_world.TOKEN, stamp, "n1", echo), "timestamp": stamp,
             "nonce": "n1", "echostr": echo}
    response = await client.get("/hooks/wecom", params=query, headers=STRANGER)
    assert response.status_code == 200 and response.text == "8812763309414513"
    again = await client.get("/hooks/wecom", params=query)
    assert again.status_code == 403 and again.content == b""          # a URL check is answered once


async def test_a_signed_message_is_taken_in_answered_at_once_and_stored_in_english_with_the_original(client, world):  # noqa: F811
    fake, said = world
    _closed_to_the_public(client)
    query, body = wecom_world.kf_event()
    response = await client.post("/hooks/wecom", params=query, content=body, headers=STRANGER)
    assert response.status_code == 200 and response.content == b""
    await ingest.settle()
    [thread] = store.threads()
    [message] = store.messages(thread.chat_id)
    assert message.text == "样衣好了吗？周一寄出。" and message.language == "zh"
    assert message.english == "Is the sample ready? It goes out on Monday." and message.translation == "machine translation"
    assert thread.who == "Jessica Factory" and thread.route == "kf" and thread.last_in_id == message.message_id
    # The callback's own token was used to read, and the read position was kept.
    sync = [b for p, _, b in fake.calls if p == "/kf/sync_msg"]
    assert sync == [{"open_kfid": wecom_world.KF, "limit": 1000, "voice_format": 0, "token": "ENCtoken"}]
    assert store.cursor(f"wecom:kf:{wecom_world.KF}")
    assert said == ["<message>\n样衣好了吗？周一寄出。\n</message>"]


async def test_a_repeat_of_an_accepted_callback_is_answered_and_dropped(client, world):  # noqa: F811
    fake, _ = world
    query, body = wecom_world.kf_event(nonce="same")
    first = await client.post("/hooks/wecom", params=query, content=body)
    await ingest.settle()
    second = await client.post("/hooks/wecom", params=query, content=body)
    await ingest.settle()
    assert first.status_code == second.status_code == 200 and second.content == b""
    assert len([c for c in fake.calls if c[0] == "/kf/sync_msg"]) == 1


@pytest.mark.parametrize("change", ["unsigned", "wrong_signature", "stale", "future", "other_company", "garbage"])
async def test_anything_not_signed_by_wecom_now_gets_an_empty_403_and_nothing_happens(client, world, change):  # noqa: F811
    fake, said = world
    _closed_to_the_public(client)
    stamp = int(time.time()) + (-301 if change == "stale" else 301 if change == "future" else 0)
    query, body = wecom_world.kf_event(timestamp=stamp)
    if change == "unsigned":
        query = {}
    elif change == "wrong_signature":
        query = {**query, "msg_signature": "0" * 40}
    elif change == "garbage":
        body = b"<xml><Encrypt>nope</Encrypt></xml>"
    elif change == "other_company":
        crypto = wecom_world.wecom.CallbackCrypto(wecom_world.TOKEN, wecom_world.AES, "ww_someone_else_00")
        sealed = crypto.encrypt("<xml><MsgType>event</MsgType></xml>")
        query = {**query, "msg_signature": wecom_world.wecom.signature(wecom_world.TOKEN, query["timestamp"], query["nonce"], sealed)}
        body = f"<xml><Encrypt><![CDATA[{sealed}]]></Encrypt></xml>".encode()
    for headers in ({}, STRANGER, PROXIED):
        response = await client.post("/hooks/wecom", params=query, content=body, headers=headers)
        assert response.status_code == 403 and response.content == b"", (change, headers)
    await ingest.settle()
    assert not [c for c in fake.calls if c[0] == "/kf/sync_msg"] and store.threads() == [] and said == []


async def test_a_body_over_the_cap_is_refused_before_it_is_read(client, world):  # noqa: F811
    query, _ = wecom_world.kf_event()
    big = b"<xml><Encrypt>" + b"A" * (guard_module.MAX_BODY_BYTES + 10) + b"</Encrypt></xml>"
    response = await client.post("/hooks/wecom", params=query, content=big)
    assert response.status_code == 403 and response.content == b""
    lying = await client.post("/hooks/wecom", params=query, content=b"<xml/>",
                              headers={"Content-Length": str(guard_module.MAX_BODY_BYTES + 1)})
    assert lying.status_code == 403 and lying.content == b""


async def test_a_deeply_nested_body_gets_an_empty_403_never_a_500(client, world, monkeypatch):  # noqa: F811
    """Review note 1 (8 Oct): JSON nested 30,000 deep is 60 KB, under the cap, and json.loads gives
    up with RecursionError. Anyone can post it; it must end as every other refusal does. And
    whatever else reading the envelope might throw is a refusal too."""
    import httpx

    _closed_to_the_public(client)
    query, _ = wecom_world.kf_event()
    deep = b'{"Encrypt":' + b"[" * 30_000 + b"]" * 30_000 + b"}"
    assert len(deep) < guard_module.MAX_BODY_BYTES
    with pytest.raises(wecom_world.wecom.CryptoError):
        wecom_world.wecom.envelope(deep)
    # As production answers: an exception the app did not catch would be a 500 here, not raised.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as raw:
        for headers in ({}, STRANGER):
            response = await raw.post("/hooks/wecom", params=query, content=deep, headers=headers)
            assert (response.status_code, response.content) == (403, b""), headers

        def breaks(_body):
            raise RuntimeError("anything at all")

        monkeypatch.setattr(wecom_world.wecom, "envelope", breaks)
        response = await raw.post("/hooks/wecom", params=query, content=b"<xml/>")
        assert (response.status_code, response.content) == (403, b"")


async def test_with_no_wecom_keys_the_door_is_shut(client, world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(wecom_world.wecom, "_stored", lambda name: "")
    query, body = wecom_world.kf_event()
    response = await client.post("/hooks/wecom", params=query, content=body)
    assert response.status_code == 403 and response.content == b""


async def test_only_the_exact_hook_path_skips_the_door(client, world):  # noqa: F811
    """Every near miss is judged by the door exactly as any owner route is: refused to the public."""
    _closed_to_the_public(client)
    query, body = wecom_world.kf_event()
    for path in ("/hooks", "/hooks/", "/hooks/wecom/", "/hooks/wecom/x", "/hooks/whatsapp", "/hooks/WECOM", "/hooks/wecom%2F"):
        for headers in ({}, STRANGER):
            response = await client.post(path, params=query, content=body, headers=headers)
            assert response.status_code == 403, (path, headers, response.status_code)
            assert "not allowed" in response.text, (path, headers)
    for method in ("PUT", "DELETE", "PATCH"):
        response = await client.request(method, "/hooks/wecom", params=query, content=body)
        assert response.status_code == 403 and "not allowed" in response.text, method


async def test_the_door_carries_no_authority_into_what_it_starts(client, world, monkeypatch):  # noqa: F811
    from app.tools import authority

    seen = []
    real = ingest.process

    async def watching(adapter, inbound):
        seen.append(authority.current())
        return await real(adapter, inbound)

    monkeypatch.setattr(ingest, "process", watching)
    query, body = wecom_world.kf_event()
    await client.post("/hooks/wecom", params=query, content=body, headers=PROXIED)
    await ingest.settle()
    assert seen == [None]


async def test_nothing_a_callback_carried_reaches_the_log(client, world, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    query, body = wecom_world.kf_event(nonce="lognonce")
    await client.post("/hooks/wecom", params=query, content=body)
    await client.post("/hooks/wecom", params={**query, "msg_signature": "f" * 40}, content=body)
    await ingest.settle()
    logged = caplog.text
    for private in ("样衣", "Is the sample ready", wecom_world.JESSICA, wecom_world.KF, "Jessica Factory",
                    query["msg_signature"], "lognonce", wecom_world.SECRET, wecom_world.AES, wecom_world.TOKEN):
        assert private not in logged, private


def test_the_hooks_query_never_reaches_the_access_log():
    """uvicorn's access line for the door keeps its path and loses WeCom's signature, nonce and echo."""
    from app.logging.quiet import QuietPollsFilter

    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("203.0.113.1:5", "POST", "/hooks/wecom?msg_signature=abc&timestamp=1&nonce=n", "1.1", 200), None)
    assert QuietPollsFilter().filter(record)
    assert record.args[2] == "/hooks/wecom?[not logged]"


async def test_a_body_in_utf16_is_refused_before_any_parser_sees_it(client, world, monkeypatch):  # noqa: F811
    """Review note 2 (8 Oct): a UTF-16 body declaring an entity reached the XML parser, and its
    entity was expanded, before the signature was checked. Now it is refused unread."""
    from app.clients import wecom

    parsed = []
    monkeypatch.setattr(wecom.ET, "fromstring", lambda *a, **kw: parsed.append(a) or None)
    _closed_to_the_public(client)
    query, _ = wecom_world.kf_event()
    body = '<!DOCTYPE x [<!ENTITY a "expanded">]><xml><Encrypt>&a;</Encrypt></xml>'.encode("utf-16")
    for headers in ({}, STRANGER):
        response = await client.post("/hooks/wecom", params=query, content=body, headers=headers)
        assert (response.status_code, response.content) == (403, b""), headers
    assert parsed == [] and guard_module.GUARD.refused.get("wecom:unreadable", 0) >= 2


async def test_a_team_members_message_is_stored_before_the_door_answers_however_busy(client, world, monkeypatch):  # noqa: F811
    """Review note 5 (8 Oct), through the real door: with no run free, a team member's message is on
    disk before WeCom gets its 200, and only its translation waits for the next run."""
    fake, said = world
    ingest._WAITING.clear()
    monkeypatch.setattr(ingest, "MAX_RUNNING", 0)
    query, body = wecom_world.member_text("样衣明天到。", msgid="m9001")
    response = await client.post("/hooks/wecom", params=query, content=body, headers=STRANGER)
    assert (response.status_code, response.content) == (200, b"")
    [thread] = store.threads()
    [message] = store.messages(thread.chat_id)
    assert (thread.route, message.text, message.translation_state, said) == ("member", "样衣明天到。", "pending", [])
    monkeypatch.setattr(ingest, "MAX_RUNNING", 4)
    query, body = wecom_world.kf_event(nonce="later")
    await client.post("/hooks/wecom", params=query, content=body)        # the next run makes it
    await ingest.settle()
    assert store.message(thread.chat_id, message.message_id).translation_state == "done"
    assert "<message>\n样衣明天到。\n</message>" in said
